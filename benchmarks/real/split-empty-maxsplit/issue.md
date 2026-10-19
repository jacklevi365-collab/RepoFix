split_before、split_after、split_when 在 maxsplit=0 且输入为空时返回了一个空分组，与其其他 maxsplit 值下的空输入行为不一致。空输入应返回零个分组；非空输入、maxsplit 和 split_at 的现有语义应保持不变。
