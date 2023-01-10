# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import abc
from typing import List, Dict, Optional
import urdf_parser_py.urdf as urdf
import torch

from theseus.labs.lie_functional import se3
from theseus.constants import DeviceType
from .joint import Joint, FixedJoint, RevoluteJoint, PrismaticJoint
from .link import Link


class Robot(abc.ABC):
    def __init__(self, name: str, dtype: torch.dtype = None, device: DeviceType = None):
        if dtype is None:
            dtype = torch.get_default_dtype()
        if device is None:
            device = torch.device("cpu")
        self._name: str = name
        self._dtype: torch.dtype = dtype
        self._device: torch.device = torch.device(device)
        self._dof: int = 0
        self._num_joints: int = 0
        self._num_links: int = 0
        self._joints: List[Joint] = []
        self._links: List[Link] = []
        self._joint_map: Dict[str, Joint] = {}
        self._link_map: Dict[str, Link] = {}

    @classmethod
    def from_urdf_file(
        cls, urdf_file: str, dtype: torch.dtype = None, device: DeviceType = None
    ) -> "Robot":
        if dtype is None:
            dtype = torch.get_default_dtype()
        if device is None:
            device = torch.device("cpu")

        def get_joint_type(joint: urdf.Joint):
            if joint.type == "revolute" or joint.type == "continuous":
                return RevoluteJoint
            elif joint.type == "prismatic":
                return PrismaticJoint
            elif joint.type == "fixed":
                return FixedJoint
            else:
                raise ValueError(f"{joint.type} is currently not supported.")

        def get_origin(urdf_origin: Optional[urdf.Pose] = None) -> torch.Tensor:
            origin = torch.eye(3, 4, dtype=dtype, device=device).unsqueeze(0)
            if urdf_origin is None:
                return origin

            if urdf_origin.xyz is not None:
                origin[:, :, 3] = origin.new_tensor(urdf_origin.xyz)

            if urdf_origin.rpy is not None:
                rpy = origin.new_tensor(urdf_origin.rpy)
                c3, c2, c1 = rpy.cos()
                s3, s2, s1 = rpy.sin()
                origin[:, 0, 0] = c1 * c2
                origin[:, 0, 1] = (c1 * s2 * s3) - (c3 * s1)
                origin[:, 0, 2] = (s1 * s3) + (c1 * c3 * s2)
                origin[:, 1, 0] = c2 * s1
                origin[:, 1, 1] = (c1 * c3) + (s1 * s2 * s3)
                origin[:, 1, 2] = (c3 * s1 * s2) - (c1 * s3)
                origin[:, 2, 0] = -s2
                origin[:, 2, 1] = c2 * s3
                origin[:, 2, 2] = c2 * c3

            return origin

        urdf_model = urdf.URDF.from_xml_file(urdf_file)
        robot = Robot(urdf_model.name, dtype, device)

        for urdf_link in urdf_model.links:
            link = Link(urdf_link.name)
            robot._link_map[urdf_link.name] = link

        for urdf_joint in urdf_model.joints:
            origin = get_origin(urdf_joint.origin)
            joint_type = get_joint_type(urdf_joint)
            parent = robot.link_map[urdf_joint.parent]
            child = robot.link_map[urdf_joint.child]
            if joint_type == RevoluteJoint or joint_type == PrismaticJoint:
                axis = origin.new_tensor(urdf_joint.axis)
                joint = joint_type(
                    urdf_joint.name,
                    axis,
                    parent=parent,
                    child=child,
                    origin=origin,
                )
            else:
                joint = joint_type(
                    urdf_joint.name, parent=parent, child=child, origin=origin
                )
            child.set_parent(joint)
            parent.add_child(joint)
            robot._joint_map[urdf_joint.name] = joint

        for _, link in robot.link_map.items():
            for joint in link._children:
                if isinstance(joint, FixedJoint):
                    subjoints: List[Joint] = joint.child.children
                    joint.child.set_children([])
                    for subjoint in subjoints:
                        subjoint.set_parent(link)
                        subjoint.set_origin(se3.compose(joint.origin, subjoint.origin))
                        link.children.append(subjoint)

        joints_to_visit: List[Joint] = []
        root = robot.link_map[urdf_model.get_root()]
        num_joints = 0
        root.set_id(0)
        robot._links.append(root)
        robot._dof = 0
        joints_to_visit = joints_to_visit + root.children

        while joints_to_visit:
            joint = joints_to_visit.pop(0)
            if not isinstance(joint, FixedJoint):
                joint.set_id(num_joints)
                robot._dof += joint.dof
                robot._joints.append(joint)
                num_joints = num_joints + 1
                joint.child.set_id(num_joints)
                robot._links.append(joint.child)

                joints_to_visit = joints_to_visit + joint.child.children

        for _, joint in robot.joint_map.items():
            if joint.id >= 0:
                continue
            if not isinstance(joint, FixedJoint):
                raise ValueError(f"{joint.name} is expected to a fixed joint.")
            joint.set_id(num_joints)
            robot._joints.append(joint)
            num_joints = num_joints + 1
            joint.child.set_id(num_joints)
            robot._links.append(joint.child)

        robot._num_links = len(robot.links)
        robot._num_joints = len(robot.joints)

        for link in robot.links:
            if link.parent is not None:
                link.set_ancestors(link.parent.parent.ancestors + [link.parent.parent])
                angle_ids = (
                    link.parent.parent.angle_ids
                    if isinstance(link.parent, FixedJoint)
                    else link.parent.parent.angle_ids + [link.parent.id]
                )
                link.set_angle_ids(angle_ids)

        return robot

    @property
    def name(self) -> str:
        return self._name

    @property
    def dtype(self) -> torch.dtype:
        return self._dtype

    @property
    def device(self) -> torch.device:
        return self._device

    @property
    def dof(self) -> int:
        return self._dof

    @property
    def num_joints(self) -> int:
        return self._num_joints

    @property
    def num_links(self) -> int:
        return self._num_links

    @property
    def joints(self) -> List[Joint]:
        return self._joints

    @property
    def links(self) -> List[Link]:
        return self._links

    @property
    def joint_map(self) -> Dict[str, Joint]:
        return self._joint_map

    @property
    def link_map(self) -> Dict[str, Link]:
        return self._link_map
