"""执行 i18n 正反向契约测试；使用独立临时目录，不依赖工作区布局。
Run i18n contract tests in isolated temporary directories without workspace dependencies.
"""
from pathlib import Path
import json
import re
import shutil
import subprocess
import tempfile
import tomllib

PACKAGE = Path(__file__).resolve().parents[1]
if shutil.which('typst') is None:
    raise SystemExit('未找到 Typst，请将 typst 加入 PATH。')

manifest = tomllib.loads((PACKAGE / 'typst.toml').read_text())['package']
assert manifest['entrypoint'] == 'lib.typ'
assert manifest['version'] == '0.1.0'

errors = [tomllib.loads((PACKAGE / 'i18n/errors' / name).read_text()) for name in ('en.toml', 'zh-Hans.toml')]
assert errors[0].keys() == errors[1].keys()
for key in errors[0]:
    assert set(re.findall(r'\{([^}]+)\}', errors[0][key])) == set(re.findall(r'\{([^}]+)\}', errors[1][key]))

with tempfile.TemporaryDirectory(prefix='i18n-tests-') as folder:
    ROOT = Path(folder)
    shutil.copytree(PACKAGE, ROOT / 'package', ignore=shutil.ignore_patterns('tests', '.git', '__pycache__'))
    work = ROOT / 'work'
    work.mkdir()
    prefix = '/work'
    preamble = '''#import "/package/lib.typ": *
#import "/package/dict.typ": i18n-dict-check
#import "/package/item.typ": i18n-item-check
#import "/package/core.typ": i18n-item-matchers-check
#let english = (l => l == "en",)
#let config = i18n-config(matchers: english)
'''
    count = 0
    def case(name, code, error=None):
        global count
        source = work / 'case.typ'
        source.write_text(preamble + code)
        result = subprocess.run(['typst', 'compile', '--root', str(ROOT), str(source), str(work/'case.pdf')], capture_output=True, text=True)
        if error is None:
            assert result.returncode == 0, (name, result.stderr)
        else:
            assert result.returncode != 0 and error in result.stderr, (name, result.stderr)
        count += 1

    case('占位符值不再次替换', '''#import "/package/core.typ": error-message
#let message = error-message("new-key", matchers: english, fields: (file: "{key}.toml", key: "test"))
#assert(message == "File {key}.toml contains a key absent from the first file: test.")
''')
    case('检查器', '''#assert(i18n-dict-check((:)))
#assert(i18n-dict-check((a: (en: "A"))))
#assert(not i18n-dict-check((a: 1)))
#assert(not i18n-dict-check((a: (en: 1))))
#assert(not i18n-dict-check(1))
#assert(not i18n-dict-check((a: ("": "empty language"))))
#assert(i18n-item-check((:)))
#assert(not i18n-item-check((en: 1)))
#assert(not i18n-item-check(()))
#assert(not i18n-item-check(("": "empty language")))
#assert(i18n-item-matchers-check(()))
#assert(not i18n-item-matchers-check((1,)))
#assert(not i18n-item-matchers-check(1))
''')
    case('查询拒绝空语言名', '#(config.item-get)(("": "empty language"))', errors[0]['item'])
    case('提取拒绝空语言名', '#(config.item-from)((a: ("": "empty language")), "a")', errors[0]['dict'])
    case('前缀匹配顺序与精确优先', '''#let broad = (l => l.starts-with("zh"),)
#assert(i18n-item-get(("zh-Hant": "T", "zh-Hans": "S"), matchers: broad) == "T")
#assert(i18n-item-get(("zh-Hans": "S", "zh-Hant": "T"), matchers: broad) == "S")
#assert(i18n-item-get(("zh-Hant": "T", "zh-Hans": "S")) == "S")
''')
    case('默认优先级', '''#assert(i18n-item-get((en: "E", "zh-Hant": "T", "zh-Hans": "S")) == "S")
#assert(i18n-item-get((en: "E", zh: "C")) == "C")
#assert(i18n-item-get((en: "E")) == "E")
#assert(i18n-item-get((en: "")) == "")
#assert(i18n-item-get((EN: "E"), allow-empty: true) == none)
#assert(i18n-item-get((en: "E"), matchers: (), allow-empty: true) == none)
''')
    case('优先级与捕获', '''#let item = (en: "E", "zh-Hans": "S")
#assert((config.item-get)(item) == "E")
#assert((config.item-get)(item, matchers: (l => l == "zh-Hans",)) == "S")
#assert(i18n-item-get(item, matchers: (l => l == "fr", l => l == "en")) == "E")
#assert((config.item-from)((a: item), "a") == item)
#assert((config.item-from)((:), "missing", allow-empty: true) == (:))
''')
    case('成功查询不执行错误匹配', '''#let matcher = l => { assert(l == "custom"); true }
#assert(i18n-item-get((custom: "OK"), matchers: (matcher,)) == "OK")
#let unused = i18n-config(matchers: (matcher,))
''')
    for expr, key in [
        ('(config.item-get)(1)', 'item'),
        ('(config.item-get)((en: "E"), allow-empty: 1)', 'boolean'),
        ('(config.item-get)((en: "E"), matchers: (1,))', 'matchers'),
        ('i18n-config(matchers: 1)', 'matchers'),
        ('(config.item-from)(1, "a")', 'dict'),
        ('(config.item-from)((:), 1)', 'key'),
        ('(config.item-from)((:), "a", allow-empty: 1)', 'boolean'),
        ('(config.item-from)((:), "a")', 'absent'),
        ('(config.item-get)((:))', 'no-match'),
    ]:
        # 无法使用非法匹配器选择语言时，采用中文固定策略。
        # Use a fixed Chinese fallback when invalid matchers cannot select a language.
        language = 1 if key == 'matchers' else 0
        expected = errors[language][key].split('{')[0]
        case(expr, '#' + expr, expected)
    case('匹配器非 bool', '#i18n-item-get((en: "E"), matchers: (l => 1,))', errors[1]['matcher-result'])
    case('中文错误', '#i18n-item-from((:), "a")', '多语言字典中不存在键')
    case('未知策略兜底', '#i18n-item-get((:), matchers: (l => l == "fr",))', errors[1]['no-match'])
    case('立即 panic', '#let unused = (config.panic)((custom: (en: "immediate", "zh-Hans": "立即")), "custom")', 'immediate')
    case('panic 类型检查', '#(config.panic)(1, "custom")', errors[0]['dict'])

    case('自定义中文 panic', '#i18n-panic((custom: (en: "Custom error", "zh-Hans": "用户自定义错误")), "custom")', '用户自定义错误')
    case('panic 缺失键', '#(config.panic)((:), "missing")', errors[0]['absent'].replace('{key}', 'missing'))
    case('panic 键类型检查', '#(config.panic)((:), 1)', errors[0]['key'])
    case('panic 单次覆盖匹配器', '#(config.panic)((custom: (en: "English error", "zh-Hans": "中文错误")), "custom", matchers: (l => l == "zh-Hans",))', '中文错误')

    fixtures = work/'fixtures'
    fixtures.mkdir()
    def fixture(name, value):
        path = fixtures/name
        path.mkdir(exist_ok=True)
        for file, text in value.items():
            (path/file).write_text(text)
        return '(' + ', '.join(json.dumps(file.removesuffix('.toml')) + ': ' + json.dumps(prefix + '/fixtures/' + name + '/' + file) for file in value) + ')'
    good = fixture('good', {'en.toml': 'a="A"\nb=""\n', 'zh-Hans.toml': 'a="甲"\nb="乙"\n'})
    case('文件加载及绑定', f'''#let d = (config.dict-from)({good})
#assert(d.a.en == "A")
#assert(d.a.at("zh-Hans") == "甲")
#assert(d.b.en == "")
#assert(i18n-dict-check(d))
#assert(i18n-dict-from((:)) == (:))
''')
    added = fixture('added', {'en.toml': 'a="A"\n', 'zh-Hans.toml': 'a="甲"\nb="乙"\n'})
    missing = fixture('missing', {'en.toml': 'a="A"\nb="B"\n', 'zh-Hans.toml': 'a="甲"\n'})
    case('新增键', f'#(config.dict-from)({added})', 'contains a key absent')
    case('缺失键', f'#(config.dict-from)({missing})', 'is missing a key')
    case('允许缺失', f'''#let a = (config.dict-from)({added}, allow-missing: true)
#assert(a.b == ("zh-Hans": "乙"))
#let b = (config.dict-from)({missing}, allow-missing: true)
#assert(b.b == (en: "B"))
''')
    bad = fixture('non-string', {'en.toml': 'a=1\n'})
    case('非字符串翻译', f'#(config.dict-from)({bad})', 'must be a string')
    for expr, key in [
        ('(config.dict-from)(1)', 'files'),
        ('(config.dict-from)(())', 'files'),
        ('(config.dict-from)((:), allow-missing: 1)', 'boolean'),
        ('(config.dict-from)((en: 1))', 'file-path'),
        ('(config.dict-from)(("": "unused.toml"))', 'language'),
    ]:
        case(expr, '#' + expr, errors[0][key].split('{')[0])
    case('直接覆盖加载错误语言为英文', '#i18n-dict-from((en: 1), matchers: (language => language == "en",))', errors[0]['file-path'])
    case('直接覆盖加载错误语言为中文', '#i18n-dict-from((en: 1), matchers: (language => language == "zh-Hans",))', errors[1]['file-path'])
    case('调用方相对 path 与字符串混用', '''#let dict = (config.dict-from)((
      en: path("fixtures/good/en.toml"),
      "zh-Hans": "/work/fixtures/good/zh-Hans.toml",
    ))
#assert(dict.a == (en: "A", "zh-Hans": "甲"))
''')
    case('语言名称独立于文件名', '''#let dict = i18n-dict-from((EN: path("fixtures/good/en.toml")))
#assert(dict.a == (EN: "A"))
''')
    case('path 的缺失键错误', '#(config.dict-from)((en: path("fixtures/missing/en.toml"), "zh-Hans": path("fixtures/missing/zh-Hans.toml")))', 'is missing a key')
    case('先匹配语言不是先遍历字典', '#assert(i18n-item-get((en: "E", fr: "F"), matchers: (l => l == "fr", l => l == "en")) == "F")')
    # 在隔离的本地包目录中验证清单与版本化导入。
    # Verify the manifest and versioned imports in an isolated local package directory.
    packages = ROOT / 'packages'
    installed = packages / 'local' / manifest['name'] / manifest['version']
    shutil.copytree(ROOT / 'package', installed)
    package_source = work / 'package-import.typ'
    package_source.write_text(
        '#import "@local/' + manifest['name'] + ':' + manifest['version'] + '": *\n'
        '#assert(i18n-item-get((en: "English")) == "English")\n'
        '#let configured = i18n-config(matchers: (language => language == "en",))\n'
        '#assert((configured.item-get)((en: "English", "zh-Hans": "中文")) == "English")\n'
        '#let loaded = (configured.dict-from)((en: path("fixtures/good/en.toml"), "zh-Hans": path("/fixtures/good/zh-Hans.toml")))\n'
        '#assert(loaded.a == (en: "A", "zh-Hans": "甲"))\n'
        '#let bundled = i18n-dict-from((en: "i18n/errors/en.toml"))\n'
        '#assert(bundled.item.en == "Input must be a multilingual item.")\n'


    )
    result = subprocess.run([
        'typst', 'compile', '--root', str(work), '--package-path', str(packages),
        str(package_source), str(work / 'package-import.pdf'),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    count += 1
    print(f'通过 {count} 组契约测试；双语资源键及占位符一致。')
