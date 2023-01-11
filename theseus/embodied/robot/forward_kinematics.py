# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import torch

from typing import List, Optional

from theseus.geometry.functional import se3
from .robot import Robot
from .link import Link
from .joint import Joint


# TODO: Add support for joints with DOF>1


def ForwardKinematicsFactory(robot: Robot, link_names: Optional[List[str]] = None):
    links: List[Link] = []

    if link_names is None:
        links = robot.links
    else:
        links = [robot.link_map[name] for name in link_names]

    link_ids: List[int] = [link.id for link in links]

    ancestors = []
    for link in links:
        ancestors += [anc for anc in link.ancestors]
    pose_ids = sorted(list(set([anc.id for anc in ancestors] + link_ids)))

    def _forward_kinematics_helper(angles: torch.Tensor):
        if angles.ndim != 2 or angles.shape[1] != robot.dof:
            raise ValueError(
                f"Joint angles for {robot.name} should be {robot.dof}-D vectors"
            )

        poses: List[Optional[torch.Tensor]] = [None] * robot.num_links
        poses[0] = angles.new_zeros(angles.shape[0], 3, 4)
        poses[0][:, 0, 0] = 1
        poses[0][:, 1, 1] = 1
        poses[0][:, 2, 2] = 1

        for id in pose_ids[1:]:
            curr: Link = robot.links[id]
            joint: Joint = robot.links[id].parent
            prev: Link = joint.parent
            relative_pose = (
                joint.relative_pose(angles[:, joint.id])
                if joint.id < robot.dof
                else joint.relative_pose()
            )
            poses[curr.id] = se3.compose(poses[prev.id], relative_pose)

        return poses

    def _forward_kinematics_impl(angles: torch.Tensor):
        poses = _forward_kinematics_helper(angles)
        return tuple(poses[id] for id in link_ids)

    def _jforward_kinematics_helper(
        poses: List[Optional[torch.Tensor]],
    ) -> torch.Tensor:
        jposes = poses[0].new_zeros(poses[0].shape[0], 6, robot.dof)

        for id in pose_ids[1:]:
            link: Link = robot.links[id]
            joint: Joint = link.parent
            if joint.id >= robot.dof:
                break
            jposes[:, :, joint.id : joint.id + 1] = (
                se3.adjoint(poses[link.id]) @ joint.axis
            )

        return jposes

    def _jforward_kinematics_impl(angles: torch.Tensor):
        poses = _forward_kinematics_helper(angles)
        jposes = _jforward_kinematics_helper(poses)

        rets = tuple(poses[id] for id in link_ids)
        jacs: List[torch.Tensor] = []

        for link_id in link_ids:
            pose = poses[link_id]
            jac = jposes.new_zeros(angles.shape[0], 6, robot.dof)
            sel = robot.links[link_id].angle_ids
            jac[:, :, sel] = se3.adjoint(se3.inverse(pose)) @ jposes[:, :, sel]
            jacs.append(jac)

        return jacs, rets

    class ForwardKinematics(torch.autograd.Function):
        @classmethod
        def forward(cls, ctx, angles):
            poses = _forward_kinematics_helper(angles)
            ctx.poses = poses
            rets = tuple(poses[id] for id in link_ids)
            ctx.rets = rets
            return rets

        @classmethod
        def backward(cls, ctx, *grad_outputs):
            if not hasattr(ctx, "jposes"):
                ctx.jposes: torch.Tensor = _jforward_kinematics_helper(ctx.poses)
            rets: tuple(torch.Tensor) = ctx.rets
            grad_input = grad_outputs[0].new_zeros(grad_outputs[0].shape[0], robot.dof)

            for link_id, ret, grad_output in zip(link_ids, rets, grad_outputs):
                angle_ids = robot.links[link_id].angle_ids
                temp = se3.project(
                    torch.cat(
                        (grad_output @ ret.transpose(1, 2), grad_output[:, :, 3:]),
                        dim=-1,
                    )
                ).unsqueeze(-1)
                grad_input[:, angle_ids] += (
                    ctx.jposes[:, :, angle_ids].transpose(1, 2) @ temp
                ).squeeze(-1)

            return grad_input

    return (
        ForwardKinematics,
        _forward_kinematics_impl,
        _jforward_kinematics_impl,
        _forward_kinematics_helper,
        _jforward_kinematics_helper,
    )


def get_forward_kinematics(robot: Robot, link_names: Optional[List[str]] = None):
    ForwardKinematics, _, jforward_kinematics, _, _ = ForwardKinematicsFactory(
        robot, link_names
    )
    forward_kinematics = ForwardKinematics.apply
    return forward_kinematics, jforward_kinematics