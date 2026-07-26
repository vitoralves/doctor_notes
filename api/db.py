from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Key

from api.config import AWS_REGION, DYNAMODB_TABLE

_dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
_table = _dynamodb.Table(DYNAMODB_TABLE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    return value


def create_visit(
    *,
    user_id: str,
    patient_name: str,
    date_of_visit: str,
    notes: str,
    summary: str,
    model: str,
    prompt_version: str,
    input_tokens: int,
    output_tokens: int,
) -> dict[str, Any]:
    visit_id = str(uuid4())
    created_at = _now_iso()
    item = {
        "pk": f"USER#{user_id}",
        "sk": f"VISIT#{created_at}#{visit_id}",
        "entity_type": "VISIT",
        "visit_id": visit_id,
        "user_id": user_id,
        "patient_name": patient_name,
        "date_of_visit": date_of_visit,
        "notes": notes,
        "summary": summary,
        "model": model,
        "prompt_version": prompt_version,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "created_at": created_at,
        "updated_at": created_at,
    }
    _table.put_item(Item=item)
    return _to_plain(item)


def list_visits(user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    response = _table.query(
        KeyConditionExpression=Key("pk").eq(f"USER#{user_id}")
        & Key("sk").begins_with("VISIT#"),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [_to_plain(item) for item in response.get("Items", [])]


def get_visit(user_id: str, sk: str) -> dict[str, Any] | None:
    response = _table.get_item(Key={"pk": f"USER#{user_id}", "sk": sk})
    item = response.get("Item")
    return _to_plain(item) if item else None


def increment_usage(
    user_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
) -> dict[str, Any]:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = {"pk": f"USER#{user_id}", "sk": f"USAGE#{day}"}
    response = _table.update_item(
        Key=key,
        UpdateExpression=(
            "SET entity_type = :etype, "
            "#day = if_not_exists(#day, :day), "
            "updated_at = :now "
            "ADD request_count :one, input_tokens :in_tok, output_tokens :out_tok"
        ),
        ExpressionAttributeNames={"#day": "day"},
        ExpressionAttributeValues={
            ":etype": "USAGE",
            ":day": day,
            ":now": _now_iso(),
            ":one": 1,
            ":in_tok": input_tokens,
            ":out_tok": output_tokens,
        },
        ReturnValues="ALL_NEW",
    )
    return _to_plain(response["Attributes"])


def get_usage_today(user_id: str) -> dict[str, Any]:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    response = _table.get_item(Key={"pk": f"USER#{user_id}", "sk": f"USAGE#{day}"})
    item = response.get("Item")
    if not item:
        return {
            "day": day,
            "request_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
    return _to_plain(item)
