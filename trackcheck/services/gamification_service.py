from typing import Tuple

from trackcheck.config import RANKS


def get_current_rank(total_sparks: int) -> int:
    current_rank = 1
    for rank_id, rank_data in sorted(RANKS.items()):
        if total_sparks >= rank_data["sparks_needed"]:
            current_rank = rank_id
        else:
            break
    return current_rank



def get_sparks_for_next_rank(current_rank: int, total_sparks: int) -> Tuple[int, int]:
    if current_rank >= 8:
        return (0, 365)
    next_rank = current_rank + 1
    next_sparks_needed = RANKS[next_rank]["sparks_needed"]
    sparks_needed = next_sparks_needed - total_sparks
    return (sparks_needed, next_sparks_needed)



def get_rank_emoji(rank_id: int) -> str:
    return RANKS.get(rank_id, RANKS[1])["emoji"]



def get_rank_name(rank_id: int) -> str:
    return RANKS.get(rank_id, RANKS[1])["name"]



def get_rank_motivation(rank_id: int) -> str:
    return RANKS.get(rank_id, RANKS[1])["motivation"]
