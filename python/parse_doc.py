"""把 docx / pdf / txt 解析成**带条号锚点**的合同文本。

只做解析，不判断合同内容 —— 判断在 skills/legal/verify_clauses.py。

设计上的两条硬规矩：
1. 解析不出足够文字一律**拒绝**，绝不交一份空文本往下走。
   空文本 + 会编条款的模型 = 一份看起来很专业的假风险清单，而现有任何一层都发现不了它。
   （_base.问AI 的失败返回是 `return`，不是 `raise`，错误会当正文往下流 —— 已经踩过一次。）
2. 找不到"第X条"式编号时，照样返回文本，但**带一条警告**：
   没有条号结构，逐条锚点校验就无从建立，后面的"可定位"读数不能当"已校验"看。

依赖：docx / txt 只用标准库；pdf 需要 pypdf（未安装时明确报错，不静默降级）。
"""
import io
import re
import zipfile

# 条款起始："第三条"、"第 12 条"、"第3条之1"；也吃全角数字与中文数字
条号匹配 = re.compile(r'^\s*第\s*([0-9〇一二三四五六七八九十百千零]{1,8})\s*条')
# 归一化用：NBSP / 全角空格 / 行内连续空白
空白清理 = re.compile(r'[ 　]+')


def _归一(文字):
    return 空白清理.sub(' ', (文字 or '')).strip()


def _找条号(正文):
    """从一段文字里取条号标签，取不到返回 None。原样保留中文/阿拉伯写法，
    匹配时两边都用同一份文本，不做数字换算（换算是另一处判据，别在这儿引入歧义）。"""
    m = 条号匹配.match(正文 or '')
    return m.group(1) if m else None


def _读_docx(字节):
    """docx = zip + word/document.xml。段落取 <w:p> 下的全部 <w:t>（含表格单元格里的）。

    不引 python-docx 是有意的：多一个依赖就多一份"CI 装了但本机没装"的误差，
    而这里只要段落文字。代价是丢掉表格结构 —— 合同的价款表会被拉平成几行文字，
    条款校验不受影响（锚点在条号上）。
    """
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(io.BytesIO(字节)) as 档:
        xml文本 = 档.read('word/document.xml').decode('utf-8', 'replace')
    根 = ET.fromstring(xml文本)
    段 = []
    for p in 根.iter():
        if not p.tag.endswith('}p'):
            continue
        文字 = ''.join(t.text or '' for t in p.iter() if t.tag.endswith('}t'))
        文字 = _归一(文字)
        if 文字:
            段.append(文字)
    return 段


def _读_pdf(字节, 文件名):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ValueError(
            f"解析 {文件名} 需要 pypdf，本服务未安装（pip install pypdf）。"
            "临时绕行：把合同另存为 .docx 或 .txt 再传。")
    reader = PdfReader(io.BytesIO(字节))
    段 = [_归一(页.extract_text() or '') for 页 in reader.pages]
    return [s for s in 段 if s]


def _读_txt(字节):
    if isinstance(字节, str):          # 允许直接喂文本，但文件入口一律给 bytes
        return [行 for 行 in (_归一(x) for x in 字节.splitlines()) if 行]
    for 编码 in ('utf-8-sig', 'utf-8', 'gb18030'):
        try:
            文 = 字节.decode(编码)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("这份 .txt 既不是 UTF-8 也不是 GB18030，读不出来（别猜编码，转存为 UTF-8）")
    return [_归一(行) for 行 in 文.splitlines() if _归一(行)]


def _重组条款(段):
    """段列表 → (带【第N条】锚点的文本, 条款表, 条数, 警告)。

    **锚点格式只有这一处实现**：上传的 docx/pdf 和用户直接粘贴的文本都走这里，
    所以 verify_clauses 拿到的条款表一定和模型看到的那份文本同源。
    反过来也定死一条：条款表**不从客户端收** —— 让客户回传一张表，
    就等于让它自己声明"我每条都对得上"。
    """
    条款, 当前号, 当前 = {}, None, []

    def 收尾():
        if not 当前:
            return
        键 = 当前号 or '前言'
        已 = 条款.get(键, '')
        条款[键] = (已 + '\n' if 已 else '') + _归一('\n'.join(当前))

    for 段文 in 段:
        号 = _找条号(段文)
        if 号:
            收尾()
            当前号, 当前 = 号, [段文]
        else:
            当前.append(段文)
    收尾()
    条数 = sum(1 for k in 条款 if k != '前言')
    # 锚点单独成行，条款正文原样保留 —— 摘录取证要拿模型引的话跟**原文**逐字比
    文本 = '\n\n'.join(f"【第{k}条】\n{v}" if k != '前言' else v for k, v in 条款.items())
    警告 = []
    if 条数 == 0:
        警告.append(f"没找到「第X条」式编号（共 {len(段)} 段）—— 逐条锚点校验无法建立，"
                    "因此本合同的『可验证』读数不代表已校验")
    return 文本, {k: v for k, v in 条款.items() if v}, 条数, 警告


def 规范化(文本):
    """用户直接粘贴的合同 → 同一套锚点文本 + 条款表。"""
    段 = [_归一(行) for 行 in (文本 or '').splitlines() if _归一(行)]
    return _重组条款(段)


def 解析(字节, 文件名=''):
    """→ {'文本', '条款': {条号: 正文}, '条数', '警告': [], '错误'}

    '文本' 里每个条款前插了 `【第N条】` 锚点，模型按这个格式引用；
    '条款' 是给 verify_clauses 反查摘录用的同一份事实，两边不会漂移。
    """
    警告 = []
    后缀 = (文件名 or '').lower().rsplit('.', 1)[-1]
    try:
        if 后缀 == 'docx':
            段 = _读_docx(字节)
        elif 后缀 == 'pdf':
            段 = _读_pdf(字节, 文件名)
        elif 后缀 in ('txt', ''):
            段 = _读_txt(字节) if 字节 else []
        else:
            return {'文本': '', '条款': {}, '条数': 0, '警告': [],
                    '错误': f"不支持的文件类型「.{后缀}」，支持 .docx / .pdf / .txt"}
    except ValueError as e:
        return {'文本': '', '条款': {}, '条数': 0, '警告': [], '错误': str(e)}
    except zipfile.BadZipFile:
        return {'文本': '', '条款': {}, '条数': 0, '警告': [],
                '错误': "这个 .docx 其实不是 zip —— 多半是改了扩展名的 .doc（老格式）或损坏文件"}
    except Exception as e:
        # 不静默：解析失败被当"合同是空的"是最坏的形状
        return {'文本': '', '条款': {}, '条数': 0, '警告': [],
                '错误': f"解析失败 {type(e).__name__}: {str(e)[:160]}"}

    全文 = '\n'.join(段)
    if len(全文) < 50:
        return {'文本': '', '条款': {}, '条数': 0, '警告': [],
                '错误': f"只从文件里取出 {len(全文)} 字 —— 扫描件/图片型 PDF 或加密文件不支持。"
                        "请不要改用粘贴空白文本继续：那会让模型对着空气编出一整份风险清单。"}

    文本, 条款表, 条数, 无条号警告 = _重组条款(段)
    警告 += 无条号警告
    return {'文本': 文本 or 全文, '条款': 条款表, '条数': 条数,
            '警告': 警告, '错误': None}
