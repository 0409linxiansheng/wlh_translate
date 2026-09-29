import frappe
import re


def clean_all():

    print("WLH Translate Cleaner Start")

    entries = frappe.get_all(
        "Translation Entry",
        fields=[
            "name",
            "source_text"
        ]
    )

    total = len(entries)

    cleaned = 0


    for item in entries:

        text = item.source_text


        if not text:
            continue


        reason = check_text(text)


        if reason:

            frappe.db.set_value(
                "Translation Entry",
                item.name,
                {
                    "is_translatable": 0,
                    "ignore_reason": reason
                }
            )

            cleaned += 1


    frappe.db.commit()


    print(
        f"Finished: {total}, ignored: {cleaned}"
    )



def check_text(text):

    text = text.strip()


    # 日期时间
    if re.match(
        r"^\d{4}-\d{2}-\d{2}",
        text
    ):
        return "Date"



    # 纯数字
    if re.match(
        r"^[0-9\.\-\/]+$",
        text
    ):
        return "Number"



    # 文件路径
    if "/" in text and (
        "apps/" in text
        or "home/" in text
    ):
        return "File Path"



    # UUID
    if re.match(
        r"^[a-f0-9\-]{20,}$",
        text.lower()
    ):
        return "Hash"



    # 太短
    if len(text) <= 1:
        return "Too Short"


    return None
