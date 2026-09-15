#!/usr/bin/env python3
"""擴充包格式檢查。

抓的是「檔案打開來完全正常、就是打不出來」那類靜默失效——
README「五個會讓整條靜靜消失的地方」是這支的規格書。

這支只做靜態檢查，快、不用編譯。

**它看不到的東西**：一條讀音到底按不按得出來。romaji 的切分規則
（し 是 si 還是 shi、ん 要 nn、促音是子音重複、拗音兩字一組）在引擎
裡，靜態複製一份一定會漏，漏一條就把好包判成錯的。所以這裡只驗
字元，不驗「打得出來」——可疑的組合報成提醒，不報錯。

真正的判準是 tsunagi-ime 的兩支工具（把每條實際打一遍）：

    cargo run --release -p ime-core --bin spike_pack_type -- <包名>
    cargo run --release -p ime-core --bin spike_kana_roundtrip -- <讀音檔>

語言碼有五種，README 目前只寫了四種——tw（台語）沒寫。

    python tools/check_pack.py packs/範例.txt
    python tools/check_pack.py packs/          # 整個資料夾
    python tools/check_pack.py                 # 預設掃 packs/
"""

import sys
import unicodedata
from pathlib import Path

# ── 字元範圍 ────────────────────────────────────────────────────

BOPOMOFO = range(0x3105, 0x312A)          # ㄅ–ㄩ
TONES = {0x02CA, 0x02C7, 0x02CB, 0x02D9}  # ˊ ˇ ˋ ˙（一聲不標）
HIRAGANA = range(0x3041, 0x3097)          # ぁ–ゖ
KANA_EXTRA = {0x309D, 0x309E}             # ゝ ゞ 疊字記號

# tw（台語）跟 zh 同形狀但獨立一層，只給段選單用——見 pack.rs 的 "tw" 分支。
# README 目前沒寫這個語言碼。
LANGS = {"zh", "ja", "en", "sym", "tw"}
NEEDS_OUTPUT = {"zh", "ja", "sym", "tw"}  # 第三欄不能省的語言

# 檔頭認得的欄位。其他 `#` 開頭的都是純註解，放哪裡都行。
# readonly／author／homepage 是內建包在用的，README 沒寫。
HEADER_KEYS = {"name", "version", "license", "updated", "description",
               "readonly", "author", "homepage"}

# ── 單行檢查 ────────────────────────────────────────────────────


def check_entry(lang, key, output, has_third_field):
    """回傳 (錯誤, 提醒) 兩份清單。

    分兩級是因為這支只看得到字元，看不到「這串按不按得出來」。
    字元不對（片假名、羅馬字、中黑點）是確定的錯；其餘只是可疑，
    報成提醒，真正的判準是 spike_kana_roundtrip。
    """
    problems = []

    if lang not in LANGS:
        # 第一欄混進空白，多半是整行都用空白當分隔，只有某一處是 Tab。
        # 報「語言碼錯」會把人指去錯的方向。
        if lang.split() and lang.split()[0] in LANGS:
            return ["欄位之間要用 Tab，這行混了空白，整行被忽略"]
        return [f"語言碼 {lang!r} 不是 {'/'.join(sorted(LANGS))}，"
                f"整行不會生效"]

    if not key:
        problems.append("第二欄（輸入）是空的")

    if lang in NEEDS_OUTPUT and not has_third_field:
        problems.append(
            f"{lang} 的第三欄不能省，就算跟第二欄一樣也要寫滿"
        )

    if lang == "ja":
        problems += check_ja_key(key)
    elif lang == "zh":
        problems += check_zh_key(key)
    elif lang == "tw":
        problems += check_tw_key(key)
    elif lang == "en":
        problems += check_en_key(key)
    elif lang == "sym":
        problems += check_sym(key, output)

    return problems


def check_ja_key(key):
    """ja 的鍵必須是打得出來的平假名。

    長音符號 ー 是合法的——羅馬字 `ga-do` 的 `-` 就打得出 `がーど`，
    VTuber 包裡幾十條都靠它。不能出現的是中黑點 ・（沒有對應按鍵）。
    """
    problems = []

    if "・" in key:
        problems.append("鍵裡有中黑點 ・，打不出來（只能放第三欄）")

    bad = [c for c in key
           if ord(c) not in HIRAGANA
           and ord(c) not in KANA_EXTRA
           and c not in "ー・"]

    if bad:
        problems.append(
            f"鍵必須是平假名，這些不是：{describe_chars(bad)}"
        )
    return problems


def check_zh_key(key):
    """zh 的鍵必須是注音符號，不是鍵盤按鍵。"""
    bad = [c for c in key
           if ord(c) not in BOPOMOFO and ord(c) not in TONES]
    if bad:
        hint = ""
        if all(c.isascii() and c.isprintable() for c in bad):
            hint = "（看起來是鍵盤按鍵，要寫注音符號本身）"
        return [f"鍵必須是注音符號{hint}，這些不是：{describe_chars(bad)}"]
    return []


# 小寫假名不能單獨站著——它們是拗音（きゃ）、促音（っ）的一半，
# 前面一定要有東西。開頭就出現代表這個讀音按不出來。
SMALL_KANA = set("ぁぃぅぇぉっゃゅょゎ")


def suspicious_key(lang, key):
    """字元都合法、但組合起來可能打不出來的情況。

    只報提醒不報錯——真正的判準是引擎的 spike_kana_roundtrip，
    這裡看不到 romaji 的切分規則（し 是 si 還是 shi、拗音兩字一組…），
    自己重寫一份一定會漏。
    """
    if lang != "ja" or not key:
        return []

    notes = []
    if key[0] in SMALL_KANA:
        notes.append(f"讀音以小寫假名 {key[0]!r} 開頭，可能打不出來"
                     f"（用 spike_kana_roundtrip 確認）")
    if key[0] == "ー":
        notes.append("讀音以長音 ー 開頭，可能打不出來"
                     "（用 spike_kana_roundtrip 確認）")
    return notes


def check_tw_key(key):
    """tw 的鍵是**華語漢字**，不是注音也不是台羅。

    使用者打注音查到華語詞，段選單再給出台語說法——所以鍵長得跟
    第三欄一樣是漢字。一個華語詞對多個台語講法是常態，不是錯。
    """
    bad = [c for c in key if c.isascii() and c.isalpha()]
    if bad:
        return [f"tw 的鍵應該是華語漢字，不是台羅拼音："
                f"{describe_chars(bad)}"]
    return []


def check_en_key(key):
    bad = [c for c in key if not (c.isascii() and c.isalnum())]
    if bad:
        return [f"en 的鍵應該是英數字，這些不是：{describe_chars(bad)}"]
    return []


def check_sym(key, output):
    problems = []
    if not output:
        return problems
    if "　" in output:
        problems.append("符號之間用了全形空白，要用半形空白分隔")
    return problems


def describe_chars(chars):
    """把字元列成人看得懂的樣子——亂碼終端也認得出來。"""
    out = []
    for c in dict.fromkeys(chars):          # 去重、保序
        try:
            name = unicodedata.name(c)
        except ValueError:
            name = "?"
        out.append(f"{c!r}(U+{ord(c):04X} {name})")
    return "、".join(out)


# ── 整檔檢查 ────────────────────────────────────────────────────


def read_text(path):
    """回傳 (內容, 錯誤訊息)。非 UTF-8 整包不會載入。"""
    raw = path.read_bytes()

    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return None, "存成了 UTF-16，要存 UTF-8"

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, ("不是 UTF-8（記事本的「ANSI」就是這種），"
                      "整包不會載入")

    if text.startswith("﻿"):
        # BOM 能解碼，但第一行的 # 會變成 ﻿#，檔頭就認不出來
        return text.lstrip("﻿"), None

    return text, None


def check_file(path):
    """回傳 (錯誤清單, 提醒清單, 有效條目數)。"""
    errors, warnings = [], []

    text, encoding_error = read_text(path)
    if encoding_error:
        return [(0, encoding_error)], [], 0

    if path.read_bytes().startswith(b"\xef\xbb\xbf"):
        warnings.append((1, "檔案開頭有 BOM，第一行的檔頭可能認不出來"))

    entries = 0
    seen = {}                # (lang, key) -> 第一次出現的行號
    seen_entry = False       # 已經出現過詞了嗎
    has_name = False

    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()

        if not stripped:
            continue

        if stripped.startswith("#"):
            body = stripped.lstrip("#").strip()
            field = body.split(":", 1)[0].strip().lower() if ":" in body else ""

            if field == "name":
                has_name = True

            # 純註解放哪裡都行，只有真正的檔頭欄位放錯位置才要報。
            if field in HEADER_KEYS and seen_entry:
                warnings.append(
                    (lineno, f"`# {field}:` 要放在所有詞之前，"
                             f"放這裡會被當成純註解")
                )
            continue

        seen_entry = True

        if "\t" not in line:
            errors.append(
                (lineno, "沒有 Tab，欄位之間一定是 Tab 不是空白，整行被忽略")
            )
            continue

        fields = line.split("\t")
        lang = fields[0].strip()
        key = fields[1].strip() if len(fields) > 1 else ""
        output = fields[2].strip() if len(fields) > 2 else ""
        has_third = len(fields) > 2 and fields[2].strip() != ""

        if len(fields) > 3:
            warnings.append(
                (lineno, f"有 {len(fields)} 個欄位，多出來的會被忽略")
            )

        problems = check_entry(lang, key, output, has_third)
        for p in problems:
            errors.append((lineno, p))

        # 引擎照樣收這條，只是可能打不出來——不從有效條目扣掉。
        for s in suspicious_key(lang, key):
            warnings.append((lineno, s))

        if not problems:
            entries += 1

        # tw 一個華語詞對多個台語講法是正常設計（全部進段選單當候選），
        # sym 的別名也本來就會展開成多列，都不算重複。
        if key and lang in ("zh", "ja"):
            dup_key = (lang, key)
            if dup_key in seen:
                warnings.append(
                    (lineno, f"和第 {seen[dup_key]} 行的鍵重複，會互相蓋掉")
                )
            else:
                seen[dup_key] = lineno

    if not has_name:
        warnings.append((0, "沒有 `# name:`，設定頁會顯示檔名"))

    return errors, warnings, entries


# ── 輸出 ────────────────────────────────────────────────────────


MAX_SHOWN = 15   # 每檔每類最多印幾條；一個包上萬行時整串印出來沒人看得完


def show(kind, items, limit=MAX_SHOWN):
    """印問題，同一種訊息合併成一行，超過上限就收尾。"""
    grouped = {}
    for lineno, msg in items:
        grouped.setdefault(msg, []).append(lineno)

    for i, (msg, linenos) in enumerate(grouped.items()):
        if i >= limit:
            print(f"      …還有 {len(grouped) - limit} 種問題沒列出")
            break
        head = "整份檔案" if linenos == [0] else f"第 {linenos[0]} 行"
        more = f"（另外 {len(linenos) - 1} 行同樣問題）" if len(linenos) > 1 else ""
        print(f"      {kind}  {head}{more}：{msg}")


def report(path, errors, warnings, entries):
    label = path.name

    if not errors and not warnings:
        print(f"[OK]  {label}：{entries} 條，沒問題")
        return

    icon = "[!!]" if errors else "[--]"
    print(f"{icon}  {label}：{entries} 條有效"
          f"，{len(errors)} 個錯誤，{len(warnings)} 個提醒")

    show("錯誤", errors)
    show("提醒", warnings)
    print()


def main(argv):
    targets = [Path(a) for a in argv[1:]] or [Path("packs")]

    files = []
    for t in targets:
        if t.is_dir():
            files += sorted(t.glob("*.txt"))
        elif t.exists():
            files.append(t)
        else:
            print(f"找不到 {t}")
            return 2

    if not files:
        print("沒有 .txt 可檢查")
        return 2

    total_errors = 0
    for path in files:
        errors, warnings, entries = check_file(path)
        total_errors += len(errors)
        report(path, errors, warnings, entries)

    if total_errors:
        print(f"共 {total_errors} 個錯誤。"
              f"這些條目不會生效，而且輸入法不會給任何提示。")
        return 1

    print(f"檢查了 {len(files)} 個檔案，沒有錯誤。")
    return 0


if __name__ == "__main__":
    # Windows 終端預設 cp950，印假名注音會爆掉
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    sys.exit(main(sys.argv))
