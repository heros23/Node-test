from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from src.dashboard_runner import write_dashboard_payload


def refresh_reports() -> Dict[str, Any]:
    output = write_dashboard_payload()
    report_path = Path(output).resolve().parent / 'learning_report.md'
    return {
        'dashboard_data': output,
        'learning_report': str(report_path),
        'exists': report_path.exists(),
    }


if __name__ == '__main__':
    print(json.dumps(refresh_reports(), ensure_ascii=False, indent=2))
