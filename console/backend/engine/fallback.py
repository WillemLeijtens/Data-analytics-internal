"""Central fallback resolver (PROMPT.md §4) — never silent.

Every analysis asks for the level it wants; the resolver answers with what
the retailer's capability set can actually deliver plus the visible labels:

  artikel gevraagd, niet beschikbaar -> merk,   label OP MERKNIVEAU
  week gevraagd, niet beschikbaar    -> maand,  label OP MAANDNIVEAU
  winkel_id niet beschikbaar         -> handmatig winkelaantal, label SCHATTING
  banner niet beschikbaar            -> aggregatie per merk+land
"""

from __future__ import annotations

from dataclasses import dataclass, field

LABEL_MERK = "OP MERKNIVEAU"
LABEL_MAAND = "OP MAANDNIVEAU"
LABEL_SCHATTING = "SCHATTING"


@dataclass
class Resolution:
    level_used: dict = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"level_used": self.level_used, "labels": self.labels}


def resolve(caps: dict, *, artikel: bool = False, week: bool = False,
            winkel: bool = False, banner: bool = False) -> Resolution:
    """caps comes from profile.capabilities(). Flags say what the analysis
    would ideally use; the resolution says what it gets."""
    r = Resolution()
    if artikel:
        if caps.get("artikel"):
            r.level_used["detail"] = "artikel"
        else:
            r.level_used["detail"] = "merk"
            r.labels.append(LABEL_MERK)
    if week:
        if caps.get("periode") == "week":
            r.level_used["periode"] = "week"
        else:
            r.level_used["periode"] = "maand"
            r.labels.append(LABEL_MAAND)
    if winkel:
        if caps.get("winkel"):
            r.level_used["winkel"] = "feiten"
        else:
            r.level_used["winkel"] = "handmatig"
            r.labels.append(LABEL_SCHATTING)
    if banner:
        r.level_used["scope"] = "banner" if caps.get("banner") else "merk+land"
    return r
