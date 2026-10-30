# Regime Harness Scoreboard

Total experiments logged (multiple-testing disclosure): **11**
Distinct model/knob variants shown below: **9**

| model | tag | n_fitted_knobs | RPS skill 20d | CI | skill vs Naive-200 | gates | exp_id |
|---|---|---|---|---|---|---|---|
| B0_climatology | stage-b-long-sequential | 0 | 0.000 | [0.000, 0.000] | n/a (reference not yet logged) | FAIL/NA | `20260926T191638Z_B0_climatology_4954b58a12` |
| B1_naive50 | stage-b-long-sequential | 0 | -0.003 | [-0.012, 0.006] | n/a (reference not yet logged) | FAIL/NA | `20260926T191716Z_B1_naive50_9be796aeb7` |
| B2_naive200 | stage-b-long-sequential | 0 | -0.008 | [-0.018, 0.002] | n/a (reference not yet logged) | FAIL/NA | `20260926T191753Z_B2_naive200_79168b6f59` |
| R1_rule_grid | stage-b-long-sequential | 1 | -0.001 | [-0.010, 0.008] | n/a (reference not yet logged) | FAIL/NA | `20260926T191833Z_R1_rule_grid_90744a208c` |
| H1_gaussian_hmm | stage-b-long-sequential | 0 | -0.008 | [-0.014, -0.003] | n/a (reference not yet logged) | FAIL/NA | `20260926T192136Z_H1_gaussian_hmm_4954b58a12` |
| J1_jump_model | stage-b-long-sequential | 1 | -0.015 | [-0.026, -0.003] | n/a (reference not yet logged) | FAIL/NA | `20260926T192221Z_J1_jump_model_714205f844` |
| R2_rule_grid_hysteresis | stage-b-long-sequential | 2 | -0.009 | [-0.020, 0.002] | n/a (reference not yet logged) | FAIL/NA | `20260926T201531Z_R2_rule_grid_hysteresis_a57dcab750` |
| L1_multinomial_logit | stage-b-long-sequential | 1 | -0.127 | [-0.182, -0.079] | n/a (reference not yet logged) | FAIL/NA | `20260926T202041Z_L1_multinomial_logit_5520608379` |
| K1_knn_analogs | stage-b-long-sequential | 1 | -0.108 | [-0.155, -0.065] | n/a (reference not yet logged) | FAIL/NA | `20260926T202313Z_K1_knn_analogs_0913526256` |

## Gate detail (latest per variant)

### B0_climatology — `20260926T191638Z_B0_climatology_4954b58a12`

- rps_skill_20d_ci_lower_positive: FAIL
- calibration_20d_within_bound: FAIL
- flips_per_year_in_range: FAIL
- whipsaw_rate_within_bound: n/a
- mean_duration_within_bound: PASS
- prob_jump_share_within_bound: PASS
- median_lag_within_bound: PASS
- knob_perturbation_within_bound: n/a
- data_perturbation_within_bound: PASS

### B1_naive50 — `20260926T191716Z_B1_naive50_9be796aeb7`

- rps_skill_20d_ci_lower_positive: FAIL
- calibration_20d_within_bound: FAIL
- flips_per_year_in_range: FAIL
- whipsaw_rate_within_bound: FAIL
- mean_duration_within_bound: PASS
- prob_jump_share_within_bound: PASS
- median_lag_within_bound: FAIL
- knob_perturbation_within_bound: n/a
- data_perturbation_within_bound: PASS

### B2_naive200 — `20260926T191753Z_B2_naive200_79168b6f59`

- rps_skill_20d_ci_lower_positive: FAIL
- calibration_20d_within_bound: FAIL
- flips_per_year_in_range: PASS
- whipsaw_rate_within_bound: FAIL
- mean_duration_within_bound: PASS
- prob_jump_share_within_bound: PASS
- median_lag_within_bound: FAIL
- knob_perturbation_within_bound: n/a
- data_perturbation_within_bound: PASS

### R1_rule_grid — `20260926T191833Z_R1_rule_grid_90744a208c`

- rps_skill_20d_ci_lower_positive: FAIL
- calibration_20d_within_bound: FAIL
- flips_per_year_in_range: FAIL
- whipsaw_rate_within_bound: FAIL
- mean_duration_within_bound: PASS
- prob_jump_share_within_bound: PASS
- median_lag_within_bound: PASS
- knob_perturbation_within_bound: FAIL
- data_perturbation_within_bound: PASS

### H1_gaussian_hmm — `20260926T192136Z_H1_gaussian_hmm_4954b58a12`

- rps_skill_20d_ci_lower_positive: FAIL
- calibration_20d_within_bound: FAIL
- flips_per_year_in_range: PASS
- whipsaw_rate_within_bound: PASS
- mean_duration_within_bound: PASS
- prob_jump_share_within_bound: PASS
- median_lag_within_bound: PASS
- knob_perturbation_within_bound: n/a
- data_perturbation_within_bound: FAIL

### J1_jump_model — `20260926T192221Z_J1_jump_model_714205f844`

- rps_skill_20d_ci_lower_positive: FAIL
- calibration_20d_within_bound: FAIL
- flips_per_year_in_range: FAIL
- whipsaw_rate_within_bound: n/a
- mean_duration_within_bound: PASS
- prob_jump_share_within_bound: PASS
- median_lag_within_bound: PASS
- knob_perturbation_within_bound: PASS
- data_perturbation_within_bound: PASS

### R2_rule_grid_hysteresis — `20260926T201531Z_R2_rule_grid_hysteresis_a57dcab750`

- rps_skill_20d_ci_lower_positive: FAIL
- calibration_20d_within_bound: FAIL
- flips_per_year_in_range: PASS
- whipsaw_rate_within_bound: PASS
- mean_duration_within_bound: PASS
- prob_jump_share_within_bound: PASS
- median_lag_within_bound: PASS
- knob_perturbation_within_bound: FAIL
- data_perturbation_within_bound: PASS

### L1_multinomial_logit — `20260926T202041Z_L1_multinomial_logit_5520608379`

- rps_skill_20d_ci_lower_positive: FAIL
- calibration_20d_within_bound: FAIL
- flips_per_year_in_range: PASS
- whipsaw_rate_within_bound: FAIL
- mean_duration_within_bound: PASS
- prob_jump_share_within_bound: PASS
- median_lag_within_bound: PASS
- knob_perturbation_within_bound: PASS
- data_perturbation_within_bound: PASS

### K1_knn_analogs — `20260926T202313Z_K1_knn_analogs_0913526256`

- rps_skill_20d_ci_lower_positive: FAIL
- calibration_20d_within_bound: FAIL
- flips_per_year_in_range: PASS
- whipsaw_rate_within_bound: FAIL
- mean_duration_within_bound: PASS
- prob_jump_share_within_bound: PASS
- median_lag_within_bound: PASS
- knob_perturbation_within_bound: FAIL
- data_perturbation_within_bound: PASS

## Calibration plots

- B0_climatology (`20260926T191638Z_B0_climatology_4954b58a12`): research/output/regime/20260926T191638Z_B0_climatology_4954b58a12/plots/reliability_20d_bands.png
- B0_climatology (`20260926T191638Z_B0_climatology_4954b58a12`): research/output/regime/20260926T191638Z_B0_climatology_4954b58a12/plots/reliability_dd_20.png
- B0_climatology (`20260926T191638Z_B0_climatology_4954b58a12`): research/output/regime/20260926T191638Z_B0_climatology_4954b58a12/plots/reliability_dd_60.png
- B0_climatology (`20260926T191638Z_B0_climatology_4954b58a12`): research/output/regime/20260926T191638Z_B0_climatology_4954b58a12/plots/reliability_up_5.png
- B0_climatology (`20260926T191638Z_B0_climatology_4954b58a12`): research/output/regime/20260926T191638Z_B0_climatology_4954b58a12/plots/reliability_up_60.png
- B0_climatology (`20260926T191638Z_B0_climatology_4954b58a12`): research/output/regime/20260926T191638Z_B0_climatology_4954b58a12/plots/reliability_vol_high_20.png
- B1_naive50 (`20260926T191716Z_B1_naive50_9be796aeb7`): research/output/regime/20260926T191716Z_B1_naive50_9be796aeb7/plots/reliability_20d_bands.png
- B1_naive50 (`20260926T191716Z_B1_naive50_9be796aeb7`): research/output/regime/20260926T191716Z_B1_naive50_9be796aeb7/plots/reliability_dd_20.png
- B1_naive50 (`20260926T191716Z_B1_naive50_9be796aeb7`): research/output/regime/20260926T191716Z_B1_naive50_9be796aeb7/plots/reliability_dd_60.png
- B1_naive50 (`20260926T191716Z_B1_naive50_9be796aeb7`): research/output/regime/20260926T191716Z_B1_naive50_9be796aeb7/plots/reliability_up_5.png
- B1_naive50 (`20260926T191716Z_B1_naive50_9be796aeb7`): research/output/regime/20260926T191716Z_B1_naive50_9be796aeb7/plots/reliability_up_60.png
- B1_naive50 (`20260926T191716Z_B1_naive50_9be796aeb7`): research/output/regime/20260926T191716Z_B1_naive50_9be796aeb7/plots/reliability_vol_high_20.png
- B2_naive200 (`20260926T191753Z_B2_naive200_79168b6f59`): research/output/regime/20260926T191753Z_B2_naive200_79168b6f59/plots/reliability_20d_bands.png
- B2_naive200 (`20260926T191753Z_B2_naive200_79168b6f59`): research/output/regime/20260926T191753Z_B2_naive200_79168b6f59/plots/reliability_dd_20.png
- B2_naive200 (`20260926T191753Z_B2_naive200_79168b6f59`): research/output/regime/20260926T191753Z_B2_naive200_79168b6f59/plots/reliability_dd_60.png
- B2_naive200 (`20260926T191753Z_B2_naive200_79168b6f59`): research/output/regime/20260926T191753Z_B2_naive200_79168b6f59/plots/reliability_up_5.png
- B2_naive200 (`20260926T191753Z_B2_naive200_79168b6f59`): research/output/regime/20260926T191753Z_B2_naive200_79168b6f59/plots/reliability_up_60.png
- B2_naive200 (`20260926T191753Z_B2_naive200_79168b6f59`): research/output/regime/20260926T191753Z_B2_naive200_79168b6f59/plots/reliability_vol_high_20.png
- R1_rule_grid (`20260926T191833Z_R1_rule_grid_90744a208c`): research/output/regime/20260926T191833Z_R1_rule_grid_90744a208c/plots/reliability_20d_bands.png
- R1_rule_grid (`20260926T191833Z_R1_rule_grid_90744a208c`): research/output/regime/20260926T191833Z_R1_rule_grid_90744a208c/plots/reliability_dd_20.png
- R1_rule_grid (`20260926T191833Z_R1_rule_grid_90744a208c`): research/output/regime/20260926T191833Z_R1_rule_grid_90744a208c/plots/reliability_dd_60.png
- R1_rule_grid (`20260926T191833Z_R1_rule_grid_90744a208c`): research/output/regime/20260926T191833Z_R1_rule_grid_90744a208c/plots/reliability_up_5.png
- R1_rule_grid (`20260926T191833Z_R1_rule_grid_90744a208c`): research/output/regime/20260926T191833Z_R1_rule_grid_90744a208c/plots/reliability_up_60.png
- R1_rule_grid (`20260926T191833Z_R1_rule_grid_90744a208c`): research/output/regime/20260926T191833Z_R1_rule_grid_90744a208c/plots/reliability_vol_high_20.png
- H1_gaussian_hmm (`20260926T192136Z_H1_gaussian_hmm_4954b58a12`): research/output/regime/20260926T192136Z_H1_gaussian_hmm_4954b58a12/plots/reliability_20d_bands.png
- H1_gaussian_hmm (`20260926T192136Z_H1_gaussian_hmm_4954b58a12`): research/output/regime/20260926T192136Z_H1_gaussian_hmm_4954b58a12/plots/reliability_dd_20.png
- H1_gaussian_hmm (`20260926T192136Z_H1_gaussian_hmm_4954b58a12`): research/output/regime/20260926T192136Z_H1_gaussian_hmm_4954b58a12/plots/reliability_dd_60.png
- H1_gaussian_hmm (`20260926T192136Z_H1_gaussian_hmm_4954b58a12`): research/output/regime/20260926T192136Z_H1_gaussian_hmm_4954b58a12/plots/reliability_up_5.png
- H1_gaussian_hmm (`20260926T192136Z_H1_gaussian_hmm_4954b58a12`): research/output/regime/20260926T192136Z_H1_gaussian_hmm_4954b58a12/plots/reliability_up_60.png
- H1_gaussian_hmm (`20260926T192136Z_H1_gaussian_hmm_4954b58a12`): research/output/regime/20260926T192136Z_H1_gaussian_hmm_4954b58a12/plots/reliability_vol_high_20.png
- J1_jump_model (`20260926T192221Z_J1_jump_model_714205f844`): research/output/regime/20260926T192221Z_J1_jump_model_714205f844/plots/reliability_20d_bands.png
- J1_jump_model (`20260926T192221Z_J1_jump_model_714205f844`): research/output/regime/20260926T192221Z_J1_jump_model_714205f844/plots/reliability_dd_20.png
- J1_jump_model (`20260926T192221Z_J1_jump_model_714205f844`): research/output/regime/20260926T192221Z_J1_jump_model_714205f844/plots/reliability_dd_60.png
- J1_jump_model (`20260926T192221Z_J1_jump_model_714205f844`): research/output/regime/20260926T192221Z_J1_jump_model_714205f844/plots/reliability_up_5.png
- J1_jump_model (`20260926T192221Z_J1_jump_model_714205f844`): research/output/regime/20260926T192221Z_J1_jump_model_714205f844/plots/reliability_up_60.png
- J1_jump_model (`20260926T192221Z_J1_jump_model_714205f844`): research/output/regime/20260926T192221Z_J1_jump_model_714205f844/plots/reliability_vol_high_20.png
- R2_rule_grid_hysteresis (`20260926T201531Z_R2_rule_grid_hysteresis_a57dcab750`): research/output/regime/20260926T201531Z_R2_rule_grid_hysteresis_a57dcab750/plots/reliability_20d_bands.png
- R2_rule_grid_hysteresis (`20260926T201531Z_R2_rule_grid_hysteresis_a57dcab750`): research/output/regime/20260926T201531Z_R2_rule_grid_hysteresis_a57dcab750/plots/reliability_dd_20.png
- R2_rule_grid_hysteresis (`20260926T201531Z_R2_rule_grid_hysteresis_a57dcab750`): research/output/regime/20260926T201531Z_R2_rule_grid_hysteresis_a57dcab750/plots/reliability_dd_60.png
- R2_rule_grid_hysteresis (`20260926T201531Z_R2_rule_grid_hysteresis_a57dcab750`): research/output/regime/20260926T201531Z_R2_rule_grid_hysteresis_a57dcab750/plots/reliability_up_5.png
- R2_rule_grid_hysteresis (`20260926T201531Z_R2_rule_grid_hysteresis_a57dcab750`): research/output/regime/20260926T201531Z_R2_rule_grid_hysteresis_a57dcab750/plots/reliability_up_60.png
- R2_rule_grid_hysteresis (`20260926T201531Z_R2_rule_grid_hysteresis_a57dcab750`): research/output/regime/20260926T201531Z_R2_rule_grid_hysteresis_a57dcab750/plots/reliability_vol_high_20.png
- L1_multinomial_logit (`20260926T202041Z_L1_multinomial_logit_5520608379`): research/output/regime/20260926T202041Z_L1_multinomial_logit_5520608379/plots/reliability_20d_bands.png
- L1_multinomial_logit (`20260926T202041Z_L1_multinomial_logit_5520608379`): research/output/regime/20260926T202041Z_L1_multinomial_logit_5520608379/plots/reliability_dd_20.png
- L1_multinomial_logit (`20260926T202041Z_L1_multinomial_logit_5520608379`): research/output/regime/20260926T202041Z_L1_multinomial_logit_5520608379/plots/reliability_dd_60.png
- L1_multinomial_logit (`20260926T202041Z_L1_multinomial_logit_5520608379`): research/output/regime/20260926T202041Z_L1_multinomial_logit_5520608379/plots/reliability_up_5.png
- L1_multinomial_logit (`20260926T202041Z_L1_multinomial_logit_5520608379`): research/output/regime/20260926T202041Z_L1_multinomial_logit_5520608379/plots/reliability_up_60.png
- L1_multinomial_logit (`20260926T202041Z_L1_multinomial_logit_5520608379`): research/output/regime/20260926T202041Z_L1_multinomial_logit_5520608379/plots/reliability_vol_high_20.png
- K1_knn_analogs (`20260926T202313Z_K1_knn_analogs_0913526256`): research/output/regime/20260926T202313Z_K1_knn_analogs_0913526256/plots/reliability_20d_bands.png
- K1_knn_analogs (`20260926T202313Z_K1_knn_analogs_0913526256`): research/output/regime/20260926T202313Z_K1_knn_analogs_0913526256/plots/reliability_dd_20.png
- K1_knn_analogs (`20260926T202313Z_K1_knn_analogs_0913526256`): research/output/regime/20260926T202313Z_K1_knn_analogs_0913526256/plots/reliability_dd_60.png
- K1_knn_analogs (`20260926T202313Z_K1_knn_analogs_0913526256`): research/output/regime/20260926T202313Z_K1_knn_analogs_0913526256/plots/reliability_up_5.png
- K1_knn_analogs (`20260926T202313Z_K1_knn_analogs_0913526256`): research/output/regime/20260926T202313Z_K1_knn_analogs_0913526256/plots/reliability_up_60.png
- K1_knn_analogs (`20260926T202313Z_K1_knn_analogs_0913526256`): research/output/regime/20260926T202313Z_K1_knn_analogs_0913526256/plots/reliability_vol_high_20.png

