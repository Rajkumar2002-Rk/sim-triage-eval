"""Write the Agent block's response format from schema.py (single source of truth)."""
import json

from simtriage import schema

s = schema.Triage.model_json_schema()
for prop in s["properties"].values():
    prop.pop("title", None)
s.pop("title", None)
s.pop("description", None)  # the docstring is for developers, not the model
s["additionalProperties"] = False
json.dump({"name": "triage", "strict": True, "schema": s},
          open("prompts/response_format.json", "w"), indent=2)
print(json.dumps(s, indent=1)[:900])
