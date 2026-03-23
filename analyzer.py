import re


def parse_title(text: str):

    result = {
        "publish": None,
        "author": None,
        "author_tag": None,
        "title": "",
        "remarks": []
    }

    s = text.strip()

    # 1 parse publish
    m = re.match(r'^\(([^()]+)\)', s)
    if m:
        result["publish"] = m.group(1)
        s = s[m.end():].strip()

    # 2 find all []
    brackets = list(re.finditer(r'\[([^\]]+)\]', s))

    # 3 extract title
    title = re.sub(r'\[[^\]]+\]', '', s).strip()
    result["title"] = title

    title_pos = s.find(title) if title else -1

    author_index = None

    # 4 last [] before title is author
    for i, b in enumerate(brackets):
        if b.start() < title_pos:
            author_index = i

    if author_index is not None:
        author = brackets[author_index].group(1)
        result["author"] = author
        author_left_index = author.find('(')
        author_right_index = author.rfind(')')
        if author_left_index > 0:
            if author_right_index > author_left_index:
                result["author_tag"] = author[author_left_index + 1:author_right_index]
            else:
                result["author_tag"] = author[author_left_index + 1:]
        else:
            result["author_tag"] = author

    # 5 remaining [] are remarks
    for i, b in enumerate(brackets):
        if i != author_index:
            result["remarks"].append(b.group(1))

    return result


if __name__ == "__main__":
    tests = [
        "(2025)[作者(作者)]标题[备注]",
        "(2025)[作者(作者)]标题",
        "[作者(作者)]标题[备注]",
        "[备注][作者(作者)]标题[备注2]",
        "[作者]标题",
        "(2024)[作者]标题[备注1][备注2]"
    ]

    for t in tests:
        print(t)
        print(parse_title(t))
        print()
