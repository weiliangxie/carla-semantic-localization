"""This script runs specified evaluations automatically."""
# %% Imports
import os
import argparse
import pickle

import yaml
import numpy as np
import matplotlib.pyplot as plt

from carlasim.utils import TrafficSignType
import localization.eval.utils as evtools


# %% ############### Set matplotlib's format ###############
plt.rc('text', usetex=True)
plt.rc('font', family='serif', size=12)

# matplotlib.use("pgf")
# matplotlib.rcParams.update({
#     "pgf.texsystem": "pdflatex",
#     'font.family': 'serif',
#     'text.usetex': True,
#     'pgf.rcfonts': False,
# })

# %%


def remove_prefix(text, prefix):
    if text.startswith(prefix):
        return text[len(prefix):]
    return text


def get_subdir_names(directory):
    """
    # Ref: https://stackoverflow.com/questions/973473/getting-a-list-of-all-subdirectories-in-the-current-directory
    """
    return next(os.walk(directory))[1]


def set_box_color(bp, color):
    plt.setp(bp['boxes'], color=color)
    plt.setp(bp['whiskers'], color=color)
    plt.setp(bp['caps'], color=color)
    plt.setp(bp['medians'], color=color)


# %%  ############### Set directories manually ###############
RECORDING_NAME = 'urban'
TEST_NAME = 'test_configs_of_factors'
NOISE_CONFIG_LABELS = ['w/o GNSS bias', 'w/ GNSS bias']
SW_CONFIG_LABELS = ['gnss+lane', 'gnss+lane+pole', 'gnss+lane+pole+stop']

recording_dir = os.path.join('recordings', RECORDING_NAME)
test_dir = os.path.join(recording_dir, 'results', TEST_NAME)
print('Recording: {}'.format(RECORDING_NAME))
print('Test Name: {}'.format(TEST_NAME))

# %% ############### Load carla simulation configs ###############
path_to_config = os.path.join(recording_dir,
                              'settings/config.yaml')
with open(path_to_config, 'r') as f:
    carla_config = yaml.safe_load(f)

# %% ############### Load results with same noise level ###############
# Get all noise level subdirectories under the test folder
noise_configs = get_subdir_names(test_dir)

results_in_all_tests = {}
# Loop over noise levels
for noise_config in noise_configs:
    # Create a dict for this noise level
    shorten_noise_level_name = remove_prefix(noise_config, 'n_')
    results_in_all_tests[shorten_noise_level_name] = {}

    # Find sw configs in this noise level
    noise_level_dir = os.path.join(test_dir, noise_config)
    sw_configs = get_subdir_names(noise_level_dir)
    # Loop over sw configs
    for sw_config in sw_configs:
        result_dir = os.path.join(noise_level_dir, sw_config)
        path_to_result_file = os.path.join(result_dir,
                                           'results.pkl')
        with open(path_to_result_file, 'rb') as f:
            localization_results = pickle.load(f)

        shorten_config_name = remove_prefix(sw_config, 'sw_')
        results_in_all_tests[shorten_noise_level_name][shorten_config_name] = localization_results

# %% ############### Evaluate errors across all configs ###############

# Use the order of configs defined in scenarios.yaml
with open('settings/tests/scenarios.yaml', 'r') as f:
    scenarios = yaml.safe_load(f)

noise_config_file_names = scenarios[TEST_NAME][RECORDING_NAME]['noise_configs']
sw_config_file_names = scenarios[TEST_NAME][RECORDING_NAME]['sw_configs']

abs_lon_err_dict = {}
abs_lat_err_dict = {}
abs_yaw_err_dict = {}

for noise_config_file_name in noise_config_file_names:
    noise_config = os.path.splitext(noise_config_file_name)[0]
    noise_config = remove_prefix(noise_config, 'n_')

    print('')

    for sw_config_file_name in sw_config_file_names:
        sw_config = os.path.splitext(sw_config_file_name)[0]
        sw_config = remove_prefix(sw_config, 'sw_')

        results = results_in_all_tests[noise_config][sw_config]
        lon_errs = results['lon_errs']
        lat_errs = results['lat_errs']
        yaw_errs = results['yaw_errs']

        if sw_config not in abs_lon_err_dict:
            abs_lon_err_dict[sw_config] = {}
            abs_lat_err_dict[sw_config] = {}
            abs_yaw_err_dict[sw_config] = {}

        lon_abs_errs = np.abs(np.asarray(lon_errs))
        lat_abs_errs = np.abs(np.asarray(lat_errs))
        yaw_abs_errs = np.abs(np.asarray(yaw_errs))

        abs_lon_err_dict[sw_config][noise_config] = lon_abs_errs
        abs_lat_err_dict[sw_config][noise_config] = lat_abs_errs
        abs_yaw_err_dict[sw_config][noise_config] = yaw_abs_errs

        print('{}, {}:'.format(noise_config, sw_config))
        print('  Lon mean abs error: {}'.format(lon_abs_errs.mean()))
        print('  Lon median abs error: {}'.format(np.median(lon_abs_errs)))
        print('  Lat mean abs error: {}'.format(lat_abs_errs.mean()))
        print('  Lat median abs error: {}'.format(np.median(lat_abs_errs)))
        print('  Yaw mean abs error: {}'.format(yaw_abs_errs.mean()))
        print('  Yaw median abs error: {}'.format(np.median(yaw_abs_errs)))

# Number of configs
# Used for boxplot spacing
num_sw_configs = len(sw_config_file_names)
num_noise_configs = len(noise_config_file_names)

# sw_config_names = []
# noise_config_names = []

# for sw_config_file_name in sw_config_file_names:
#     sw_config_name = os.path.splitext(sw_config_file_name)[0]
#     sw_config_names.append(remove_prefix(sw_config_name, 'sw_'))
# for noise_config_file_name in noise_config_file_names:
#     noise_config_name = os.path.splitext(noise_config_file_name)[0]
#     noise_config_names.append(remove_prefix(noise_config_name, 'n_'))

flier = dict(markeredgecolor='gray', marker='+')
colors = ['tab:blue', 'tab:orange', 'tab:green', 'tab:red']
fig, axs = plt.subplots(1, 3)
for idx, (lon_errs, lat_errs, yaw_errs) in enumerate(zip(abs_lon_err_dict.values(),
                                                         abs_lat_err_dict.values(),
                                                         abs_yaw_err_dict.values())):
    list_of_lon_errs = [err for err in lon_errs.values()]
    list_of_lat_errs = [err for err in lat_errs.values()]
    list_of_yaw_errs = [err for err in yaw_errs.values()]

    positions = np.linspace(0, (num_sw_configs+1) *
                            (num_noise_configs-1), num_noise_configs, dtype=int)
    positions += idx

    # Box plot of a sw config under different noise configs
    bp = axs[0].boxplot(list_of_lon_errs, positions=positions, flierprops=flier)
    set_box_color(bp, colors[idx])
    axs[0].plot([], c=colors[idx], label=SW_CONFIG_LABELS[idx])

    # Box plot of a sw config under different noise configs
    bp = axs[1].boxplot(list_of_lat_errs, positions=positions, flierprops=flier)
    set_box_color(bp, colors[idx])
    axs[1].plot([], c=colors[idx], label=SW_CONFIG_LABELS[idx])

    # Box plot of a sw config under different noise configs
    bp = axs[2].boxplot(list_of_yaw_errs, positions=positions, flierprops=flier)
    set_box_color(bp, colors[idx])
    axs[2].plot([], c=colors[idx], label=SW_CONFIG_LABELS[idx])


axs[0].set_ylabel('abs lon err [m]')
axs[1].set_ylabel('abs lat err [m]')
axs[2].set_ylabel('abs yaw err [rad]')

first_mid = (num_sw_configs-1)/2
tick_positions = first_mid + np.arange(num_noise_configs)*(num_sw_configs+1)
for ax in axs:
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(NOISE_CONFIG_LABELS)
    ax.yaxis.grid()

fig.set_size_inches(10, 3)
axs[0].legend(framealpha=1.0, prop={'size': 6})
fig.tight_layout()
plt.show()


# %%
