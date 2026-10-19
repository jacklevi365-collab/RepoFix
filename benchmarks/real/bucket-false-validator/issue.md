bucket 忽略了布尔值为假的合法 validator callable，导致本应拒绝的键也能取值和被报告为存在。请保留自定义 callable 的行为，同时保留未传 validator 时接受所有键的行为。
