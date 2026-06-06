import json
import re

summary_obj = {
  "skills": {
    "Frameworks": ["Flask", "Django", "React"],
    "Tools": ["Docker", "Git"]
  }
}
raw_text = json.dumps(summary_obj).lower()

allowed_categories = {"Frameworks", "Tools"}

_FRAMEWORKS = {"flask", "django", "react"}
_GENERAL_TOOLS = {"docker", "git"}

_CLASSIFICATION_BUCKETS = [
    ("Frameworks", _FRAMEWORKS),
    ("Tools", _GENERAL_TOOLS),
]

techs = set()
for category_name, category_items in _CLASSIFICATION_BUCKETS:
    if category_name in allowed_categories:
        for item in category_items:
            pattern = r"(?<![a-z0-9+#.-])" + re.escape(item) + r"(?![a-z0-9+#.-])"
            if re.search(pattern, raw_text):
                techs.add(item)
print("Found:", techs)
