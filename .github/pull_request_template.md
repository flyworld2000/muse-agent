## 变更目的

说明本次修改解决的问题，以及预期结果。

## 修改内容

-
-
-

## 测试结果

- [ ] 主项目 pytest 通过
- [ ] Executor unittest 通过
- [ ] GitHub Actions CI 通过

测试命令：

```bash
python -m pytest -q tests/
python -m unittest discover -s executor -p 'test_*.py' -v
```


## 数据库安全检查
- [ ] 没有未经审查的数据库结构变更
- [ ] 没有修改生产数据库
- [ ] 数据库迁移版本检查正确
- [ ] 测试使用独立临时数据库

## 安全检查
- [ ] 没有提交 .env、密码、Token 或私钥
- [ ] 没有提交生产 SQLite 数据库或备份
- [ ] 没有暴露生产凭据
- [ ] 没有绕过 Executor 审批机制

## AI 代码审查
- [ ] 已按照 .github/AI_REVIEW.md 完成审查
- [ ] Critical 和 High 问题已解决
- [ ] AI 审查结论已由人工检查

## 人工审核
- [ ] 已检查代码变更
- [ ] 已确认测试结果
- [ ] 已确认可以合并
