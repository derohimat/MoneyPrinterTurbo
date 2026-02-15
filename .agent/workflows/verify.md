---
description: How to verify Python files (syntax check, tests)
---

// turbo-all

1. Syntax check on changed Python files:
```
python -c "import ast; files=['<file1>','<file2>']; [print(f'{f}: OK') if ast.parse(open(f,encoding='utf-8').read()) else None for f in files]"
```

2. Check git status:
```
git status
```

3. View recent git log:
```
git log -n 3 --oneline
```
