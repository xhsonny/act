import IPython
import matplotlib.pyplot as plt
import numpy as np
from pyquaternion import Quaternion

from constants import SIM_TASK_CONFIGS
from ee_sim_env import make_ee_sim_env

e = IPython.embed


class BasePolicy:
    def __init__(self, inject_noise=False):
        self.inject_noise = inject_noise
        self.step_count = 0
        self.right_trajectory = None

    def generate_trajectory(self, ts_first):
        raise NotImplementedError

    @staticmethod
    def interpolate(curr_waypoint, next_waypoint, t):
        t_frac = (t - curr_waypoint["t"]) / (next_waypoint["t"] - curr_waypoint["t"])
        curr_xyz = curr_waypoint["xyz"]
        curr_quat = curr_waypoint["quat"]
        curr_grip = curr_waypoint["gripper"]
        next_xyz = next_waypoint["xyz"]
        next_quat = next_waypoint["quat"]
        next_grip = next_waypoint["gripper"]
        xyz = curr_xyz + (next_xyz - curr_xyz) * t_frac
        quat = curr_quat + (next_quat - curr_quat) * t_frac
        gripper = curr_grip + (next_grip - curr_grip) * t_frac
        return xyz, quat, gripper

    def __call__(self, ts):
        # generate trajectory at first timestep, then open-loop execution
        if self.step_count == 0:
            self.generate_trajectory(ts)

        # Sanity check
        if self.right_trajectory is None:
            raise ValueError("right_trajectory cannot be None")

        if self.right_trajectory[0]["t"] == self.step_count:
            self.curr_right_waypoint = self.right_trajectory.pop(0)
        next_right_waypoint = self.right_trajectory[0]

        # interpolate between waypoints to obtain current pose and gripper command
        right_xyz, right_quat, right_gripper = self.interpolate(
            self.curr_right_waypoint, next_right_waypoint, self.step_count
        )

        # Inject noise
        if self.inject_noise:
            scale = 0.01
            right_xyz = right_xyz + np.random.uniform(-scale, scale, right_xyz.shape)

        action_right = np.concatenate([right_xyz, right_quat, [right_gripper]])

        self.step_count += 1
        return action_right


class PickAndTransferPolicySingleArm(BasePolicy):

    def generate_trajectory(self, ts_first):
        init_mocap_pose_right = ts_first.observation["mocap_pose_right"]

        box_info = np.array(ts_first.observation["env_state"])
        box_xyz = box_info[:3]
        box_quat = box_info[3:]
        # print(f"Generate trajectory for {box_xyz=}")

        gripper_pick_quat = Quaternion(init_mocap_pose_right[3:])
        gripper_pick_quat = gripper_pick_quat * Quaternion(axis=[0.0, 1.0, 0.0], degrees=-60)

        drop_xyz = np.array([0, 0.5, 0.15])

        self.right_trajectory = [
            {"t": 0, "xyz": init_mocap_pose_right[:3], "quat": init_mocap_pose_right[3:], "gripper": 0},  # sleep
            {
                "t": 90,
                "xyz": box_xyz + np.array([0, 0, 0.08]),
                "quat": gripper_pick_quat.elements,
                "gripper": 1,
            },  # approach the cube
            {
                "t": 130,
                "xyz": box_xyz + np.array([0, 0, -0.015]),
                "quat": gripper_pick_quat.elements,
                "gripper": 1,
            },  # go down
            {
                "t": 170,
                "xyz": box_xyz + np.array([0, 0, -0.015]),
                "quat": gripper_pick_quat.elements,
                "gripper": 0,
            },  # close gripper
            {"t": 200, "xyz": drop_xyz, "quat": gripper_pick_quat.elements, "gripper": 1},  # open gripper
            {
                "t": 260,
                "xyz": drop_xyz + np.array([0.1, 0, 0]),
                "quat": gripper_pick_quat.elements,
                "gripper": 1,
            },  # move to right
        ]


def test_policy(task_name):
    # example rolling out pick_and_transfer policy
    onscreen_render = True
    inject_noise = False

    # setup the environment
    episode_len = SIM_TASK_CONFIGS[task_name]["episode_len"]
    if task_name == "sim_transfer_cube_scripted":
        env = make_ee_sim_env("sim_transfer_cube")
    elif task_name == "sim_insertion":
        env = make_ee_sim_env("sim_insertion")
    elif task_name == "single_arm_sim_transfer_cube_scripted":
        env = make_ee_sim_env("single_arm_sim_transfer_cube")
    else:
        raise NotImplementedError

    for episode_idx in range(2):
        ts = env.reset()
        episode = [ts]
        if onscreen_render:
            ax = plt.subplot()
            plt_img = ax.imshow(ts.observation["images"]["angle"])
            plt.ion()

        policy = PickAndTransferPolicySingleArm(inject_noise)
        for step in range(episode_len):
            action = policy(ts)
            ts = env.step(action)
            episode.append(ts)
            if onscreen_render:
                plt_img.set_data(ts.observation["images"]["angle"])
                plt.pause(0.02)
        plt.close()

        episode_return = np.sum([ts.reward for ts in episode[1:]])
        if episode_return > 0:
            print(f"{episode_idx=} Successful, {episode_return=}")
        else:
            print(f"{episode_idx=} Failed")


if __name__ == "__main__":
    test_task_name = "single_arm_sim_transfer_cube_scripted"
    test_policy(test_task_name)
