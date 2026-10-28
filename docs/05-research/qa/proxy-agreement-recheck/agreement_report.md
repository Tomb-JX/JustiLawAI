# 试标一致性报告（G0.3 口径）

- 记录数 50（缺失 无；多余 无）
- 关键分类字段 mean κ(union，至少一方有值) = **0.6912878787878788**（门槛 0.80；参与字段：['conduct.behavior_type', 'conduct.role', 'conduct.method', 'intent.profit_purpose']）
- 关键分类字段 mean κ(all，未提及计类别) = 0.8381950813691428（参考口径）
- 关键数值字段完全一致率（union） = **0.8636363636363636**（88 对；门槛 0.95）
- 关键数值字段完全一致率（双方有值，仅参考） = 0.9156626506024096（83 对）
- 门禁 G0.3 判定：**不通过**
- 证据逐字命中 813/814 = 0.9987714987714987
- 分歧条目 67 条，见 disagreements.csv

| 字段 | 类型 | 关键 | 双有值 | 至少一方有值 | κ(all) | κ(valued) | κ(union) | 数值一致率（双有值） | 数值一致率（union） | 在场一致 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| conduct.times | int |  | 14 | 23 | 0.63884430176565 | 1.0 | 0.1619433198380568 | 1.0 | 0.6086956521739131 | 0.820 |
| conduct.duration_days | float |  | 10 | 14 | 0.6641074856046064 | 0.6341463414634146 | 0.449438202247191 | 0.7 | 0.5 | 0.920 |
| conduct.cheating | bool |  | 0 | 0 | — | — | — | — | — | 1.000 |
| amounts.personal_stake | amount | ★ | 24 | 24 | 0.9165275459098496 | 0.8688524590163934 | 0.8688524590163934 | 0.875 | 0.875 | 1.000 |
| amounts.per_bet | amount |  | 3 | 5 | 0.7375328083989499 | 1.0 | 0.5238095238095237 | 1.0 | 0.6 | 0.960 |
| amounts.onsite_stake_total | amount | ★ | 16 | 16 | 0.8873027798647632 | 0.8024691358024691 | 0.8024691358024691 | 0.8125 | 0.8125 | 1.000 |
| amounts.cumulative_stake | amount |  | 3 | 5 | 0.6073298429319369 | 0.5714285714285714 | 0.31818181818181823 | 0.3333333333333333 | 0.2 | 0.960 |
| amounts.commission | amount | ★ | 2 | 3 | 0.7933884297520659 | 1.0 | 0.5714285714285714 | 1.0 | 0.6666666666666666 | 0.980 |
| amounts.illegal_gain | amount |  | 1 | 1 | 1.0 | — | — | 1.0 | 1.0 | 1.000 |
| persons.participant_count | int | ★ | 28 | 32 | 0.868559411146162 | 0.9536423841059603 | 0.805352798053528 | 0.9642857142857143 | 0.84375 | 0.920 |
| persons.cumulative_participants | int |  | 2 | 4 | 0.6539792387543251 | 1.0 | 0.38461538461538464 | 1.0 | 0.5 | 0.960 |
| persons.minors_involved | bool |  | 0 | 0 | — | — | — | — | — | 1.000 |
| persons.civil_servant | bool |  | 0 | 0 | — | — | — | — | — | 1.000 |
| persons.relatives_only | bool |  | 0 | 0 | — | — | — | — | — | 1.000 |
| persons.abroad_organized_count | int |  | 0 | 0 | — | — | — | — | — | 1.000 |
| venue.venue_type | enum |  | 40 | 40 | 0.9516441005802707 | 0.9369085173501577 | 0.9369085173501577 | — | — | 1.000 |
| intent.profit_purpose | bool | ★ | 10 | 24 | 0.4027303754266211 | — | -0.16666666666666663 | — | — | 0.720 |
| circumstances.last_prior_penalty_date | date | ★ | 2 | 2 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.000 |
| circumstances.surrendered | bool |  | 2 | 2 | 1.0 | — | — | — | — | 1.000 |
| circumstances.truthful_statement | bool |  | 7 | 7 | 1.0 | — | — | — | — | 1.000 |
| circumstances.admits_and_accepts | bool |  | 1 | 2 | 0.6575342465753422 | — | 0.0 | — | — | 0.980 |
| circumstances.remedied_consequence | bool |  | 0 | 0 | — | — | — | — | — | 1.000 |
| circumstances.victim_forgiveness | bool |  | 0 | 0 | — | — | — | — | — | 1.000 |
| circumstances.coerced_or_lured | bool |  | 0 | 0 | — | — | — | — | — | 1.000 |
| circumstances.meritorious | bool |  | 0 | 0 | — | — | — | — | — | 1.000 |
| circumstances.instigated_others | bool |  | 0 | 0 | — | — | — | — | — | 1.000 |
| circumstances.retaliation | bool |  | 0 | 0 | — | — | — | — | — | 1.000 |
| circumstances.obstructed_police | bool |  | 0 | 0 | — | — | — | — | — | 1.000 |
| circumstances.minor_circumstance | enum |  | 0 | 0 | — | — | — | — | — | 1.000 |
| circumstances.first_offense | bool |  | 7 | 9 | 0.8581560283687942 | 1.0 | 0.6326530612244898 | — | — | 0.960 |
| circumstances.violations_last_year | int |  | 3 | 5 | 0.734042553191489 | 1.0 | 0.375 | 1.0 | 0.6 | 0.960 |
| person.age | int | ★ | 11 | 11 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.000 |
| person.pregnant_or_nursing | bool |  | 5 | 14 | 0.4186046511627905 | — | -0.40000000000000013 | — | — | 0.820 |
| conduct.behavior_type | enum | ★ | 50 | 50 | 1.0 | 1.0 | 1.0 | — | — | 1.000 |
| conduct.role | enum | ★ | 50 | 50 | 1.0 | 1.0 | 1.0 | — | — | 1.000 |
| conduct.method | enum | ★ | 39 | 39 | 0.95004995004995 | 0.9318181818181818 | 0.9318181818181818 | — | — | 1.000 |
