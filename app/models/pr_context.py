from typing import List, Optional
from pydantic import BaseModel, Field
from typing import Dict, Set


class PRContext(BaseModel):
    owner: str
    repo: str
    pr_number: int
    installation_id: int
    # List of changed file paths (as provided by GitHub)
    changed_files: List[str] = Field(default_factory=list)
    # Mapping of file -> set of changed line numbers in the new file
    changed_lines_map: Dict[str, Set[int]] = Field(default_factory=dict)
    # Mapping of file -> mapping from new-file line number -> diff position
    line_position_map: Dict[str, Dict[int, int]] = Field(default_factory=dict)
    local_repo_path: Optional[str] = None
