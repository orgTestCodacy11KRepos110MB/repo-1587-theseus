# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from typing import Any, Dict, cast

import numpy as np
import torch
import torch.nn as nn

import theseus as th

from .motion_planner import MotionPlanner


class _ScalarModel(nn.Module):
    def __init__(self, hidden_size: int):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(1, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, 1),
        )

    def forward(self):
        dummy = torch.ones(1, 1).to(self.layers[0].weight.device)
        return self.layers(dummy)


class _OrderOfMagnitudeModel(nn.Module):
    def __init__(self, hidden_size: int, max_order: int):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(1, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, max_order),
            nn.ReLU(),
        )
        self.register_buffer("magnitudes", (10 ** torch.arange(max_order)).unsqueeze(0))

    def forward(self):
        dummy = torch.ones(1, 1).to(self.layers[0].weight.device)
        mag_weights = self.layers(dummy).softmax(dim=1)
        return (mag_weights * self.magnitudes).sum(dim=1, keepdim=True)


# ------------------------------------------------------------------------------------ #
# All public models in this module receive a batch of map data and return one or more
# torch tensors.
# ------------------------------------------------------------------------------------ #


class ScalarCollisionWeightModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.model = _OrderOfMagnitudeModel(10, 5)

    def forward(self, _: Dict[str, torch.Tensor]):
        return {"collision_w": self.model()}


class ScalarCollisionWeightAndCostEpstModel(nn.Module):
    def __init__(self, robot_radius: float):
        super().__init__()
        self.collision_weight_model = _OrderOfMagnitudeModel(200, 5)
        self.safety_dist_model = _ScalarModel(100)
        self.robot_radius = robot_radius

    def forward(self, _: Dict[str, torch.Tensor]):
        collision_w = self.collision_weight_model()
        safety_dist = self.safety_dist_model().sigmoid()
        return {"collision_w": collision_w, "cost_eps": safety_dist + self.robot_radius}


# High level idea: the trajectory is generated by the following sequence of steps:
#
# 1. Generate a parabola whose focus is the middle point between start and goal,
#    and whose distance between focus and vertex is the output of an MLP. Thus,
#    this part of the model learns how much it should bend outward from the straight
#    line path (and towards which side).
#
# 2. Add more precise curvatures to the trajectory by constructing a "sample" around
#    the parabola, using the Gaussian Process formulation of the original motion
#    planning problem (but ignoring obstacles). This relies on the fact that sampling
#    from the GP is equivalent to:
#
#          sample = Cholesky_Low(inverse(GP_covariance)) @ u,
#
#    where u is a multivariate vector sampled from a standard multivariate Normal
#    in the space of the GP variables.
#
#    Thus, we can generate arbitrary samples by learning the vector u to use, since
#    each value of the vector will be associated to a different trajectory. We learn the
#    vector u with another MLP, and use it to compute a fake "sample" around the
#    mean trajectory specified by the parabola.
#
#    Note: This basic model is included here for illustration purposes, and it
#    uses the map's file ID as input, so it has no ability to generalize. A more
#    practical extension would use a CNN encoder upstream to produce an input for
#    each individual map image.
class InitialTrajectoryModel(nn.Module):
    def __init__(
        self,
        planner: MotionPlanner,
        max_num_images: int = 1000,
        hid_size: int = 200,
    ):
        super().__init__()

        # This planner is only used to generate initial trajectories from a
        # multivariate gaussian around a curved trajectory,
        # and it's not part of the motion planning optimization that generates
        # the final trajectory
        self.aux_motion_planner = planner.copy(collision_weight=0.0)

        # Learns the vector u to use for generating the trajectory "sample", as
        # explained in Step 2 above.
        self.layers_u = nn.Sequential(
            nn.Linear(2 * max_num_images, hid_size),
            nn.ReLU(),
            nn.Linear(hid_size, hid_size),
            nn.ReLU(),
            nn.Linear(hid_size, 4 * (planner.num_time_steps + 1)),
        )

        # Learns a quadratic offset in normal direction to bend the mean trajectory.
        # This is the distance/direction between the parabola's focus and vertex,
        # mentioned in the Step 1 above.
        self.bend_factor = nn.Sequential(
            nn.Linear(2 * max_num_images, hid_size),
            nn.ReLU(),
            nn.Linear(hid_size, 1),
            nn.Tanh(),
        )

        def init_weights(m_):
            if isinstance(m_, nn.Linear):
                torch.nn.init.normal_(m_.weight)
                torch.nn.init.normal_(m_.bias)

        self.bend_factor.apply(init_weights)

        self.dt = planner.total_time / planner.num_time_steps

        self.num_images = max_num_images

    def forward(self, batch: Dict[str, Any]):
        device = self.aux_motion_planner.objective.device
        start = batch["expert_trajectory"][:, :2, 0].to(device)
        goal = batch["expert_trajectory"][:, :2, -1].to(device)

        one_hot_dummy = torch.zeros(start.shape[0], self.num_images * 2).to(device)
        file_ids = batch["file_id"]
        for batch_idx, fi in enumerate(file_ids):
            idx = int(fi.split("_")[1]) + int("forest" in fi) * self.num_images
            one_hot_dummy[batch_idx, idx] = 1

        # Compute straight line positions to use as mean of initial trajectory
        trajectory_len = self.aux_motion_planner.trajectory_len
        dist_vec = goal - start
        pos_incr_per_step = dist_vec / (trajectory_len - 1)
        trajectory = torch.zeros(start.shape[0], 4 * trajectory_len).to(
            device=device, dtype=start.dtype
        )
        trajectory[:, :2] = start
        for t_step in range(1, trajectory_len):
            idx = 4 * t_step
            trajectory[:, idx : idx + 2] = (
                trajectory[:, idx - 4 : idx - 2] + pos_incr_per_step
            )

        # Add the parabola bend
        bend_factor = self.bend_factor(one_hot_dummy)
        start_goal_dist = dist_vec.norm(dim=1)
        cur_t = torch.zeros_like(start_goal_dist) - start_goal_dist / 2
        c = (start_goal_dist / 2) ** 2
        angle = th.SO2(
            theta=torch.ones(dist_vec.shape[0], 1).to(device=device) * np.pi / 2
        )
        normal_vector = angle.rotate(th.Point2(tensor=dist_vec)).tensor.to(
            device=device
        )
        normal_vector /= normal_vector.norm(dim=1, keepdim=True)
        for t_step in range(1, trajectory_len):
            idx = 4 * t_step
            cur_t += start_goal_dist / (trajectory_len - 1)
            add = 2 * bend_factor * ((cur_t**2 - c) / c).view(-1, 1)
            trajectory[:, idx : idx + 2] += normal_vector * add

        # Compute resulting velocities
        for t_step in range(1, trajectory_len):
            idx = 4 * t_step
            trajectory[:, idx + 2 : idx + 4] = (
                trajectory[:, idx : idx + 2] - trajectory[:, idx - 4 : idx - 2]
            ) / self.dt

        # Finally, the final initial trajectory is further curved by a learned
        # "sample" from the GP describing the motion planning problem (ignoring
        # obstacles)
        # First, compute the covariance matrix
        with torch.no_grad():
            planner_inputs = {
                "sdf_origin": batch["sdf_origin"].to(device),
                "start": start.to(device),
                "goal": goal.to(device),
                "cell_size": batch["cell_size"].to(device),
                "sdf_data": batch["sdf_data"].to(device),
            }
            self.aux_motion_planner.objective.update(planner_inputs)

            motion_optimizer = cast(
                th.NonlinearLeastSquares, self.aux_motion_planner.layer.optimizer
            )
            linearization = cast(
                th.DenseLinearization, motion_optimizer.linear_solver.linearization
            )

            # Assign current trajectory as the mean of linearization
            for var in linearization.ordering:
                var_type, time_idx = var.name.split("_")
                assert var_type in ["pose", "vel"]
                if var_type == "pose":
                    traj_idx = int(time_idx) * 4
                if var_type == "vel":
                    traj_idx = int(time_idx) * 4 + 2
                var.update(trajectory[:, traj_idx : traj_idx + 2])

            linearization.linearize()
            cov_matrix = torch.inverse(linearization.AtA)
            lower_cov = torch.linalg.cholesky(cov_matrix)

        # Compute the u vector to generate the "sample"
        u = self.layers_u(one_hot_dummy).unsqueeze(2)
        initial_trajectory = trajectory.unsqueeze(2) + torch.matmul(lower_cov, u)

        # Construct the variable values dictionary to return
        values: Dict[str, torch.Tensor] = {}
        for t_step in range(trajectory_len):
            idx = 4 * t_step
            values[f"pose_{t_step}"] = initial_trajectory[:, idx : idx + 2, 0]
            values[f"vel_{t_step}"] = initial_trajectory[:, idx + 2 : idx + 4, 0]

        return values
