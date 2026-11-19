from dataclasses import dataclass
from typing import Any


# A scenario of the library and its information control: the scenario without one
# information treatment, the same in every other key. The treatment is the key of the
# scenario that differs: `forecasts`, `hidden` or `notice`. A built control is made
# from its scenario; any other is a scenario of the library.
@dataclass(frozen=True, slots=True, kw_only=True)
class InformationControl:
    scenario: str
    treatment: str
    control: str
    built: bool = True


INFORMATION_CONTROLS = (
    InformationControl(
        scenario="forecasts",
        treatment="forecasts",
        control="forecasts-without-forecasts",
    ),
    InformationControl(
        scenario="forecasts", treatment="hidden", control="forecasts-shown"
    ),
    InformationControl(
        scenario="hidden-groups", treatment="hidden", control="hidden-groups-shown"
    ),
    InformationControl(
        scenario="notice",
        treatment="notice",
        control="supplier-outage",
        built=False,
    ),
)

# What a scenario and its control share, per treatment: `build_controls` refuses a
# control that differs in any other key or holds other demand shocks in its forecasts.
HELD_EQUAL = {
    "forecasts": "manifest, seeds, horizon, start, demand shapes, disruptions, "
    "hidden groups",
    "hidden": "manifest, seeds, horizon, start, demand shapes, disruptions, forecasts",
    "notice": "manifest, seeds, horizon, start, demand shapes, disruptions but their "
    "notice, hidden groups, forecasts",
}


# The content of the control of a scenario: its content with the treatment taken
# away and the name of the control. Without hidden groups it is the twin that the
# informed optimizer reads.
def build_control_content(
    content: dict[str, Any], control: InformationControl
) -> dict[str, Any]:
    if control.treatment == "hidden":
        return content | {"hidden": [], "name": control.control}
    built = {key: value for key, value in content.items() if key != "forecasts"}
    return built | {"name": control.control}


# The keys of the scenario in which two contents differ, in the order of their names,
# a key left out counting as an empty list. Written or random disruptions that differ
# in their notice only give `notice`. The name and the description, which no run
# reads, are left out.
def build_differing_keys(first: dict[str, Any], second: dict[str, Any]) -> list[str]:
    differing: set[str] = set()
    for key in (first.keys() | second.keys()) - {"name", "description"}:
        first_value, second_value = first.get(key, []), second.get(key, [])
        if first_value == second_value:
            continue
        if key in ("disruptions", "random_disruptions") and without_notice(
            first_value
        ) == without_notice(second_value):
            differing.add("notice")
        else:
            differing.add(key)
    return sorted(differing)


def without_notice(disruptions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in disruption.items() if key != "notice"}
        for disruption in disruptions
    ]


# The demand shocks that the forecasts of a content hold, written and random, each with
# its notice: none without forecasts or with the duration of disruptions hidden.
def build_forecast_shocks(content: dict[str, Any]) -> list[dict[str, Any]]:
    hidden = content.get("hidden", [])
    if not content.get("forecasts") or "disruptions.duration" in hidden:
        return []
    disruptions = content.get("disruptions", []) + content.get("random_disruptions", [])
    return [
        disruption for disruption in disruptions if disruption["kind"] == "demand_shock"
    ]


# The information controls of the chosen scenarios, each with its content: a built
# control is built from its scenario, any other keeps its file. A control that
# differs from its scenario in more than its treatment, or whose forecasts hold other
# demand shocks under any treatment but `forecasts`, is refused with ValueError.
def build_controls(
    library: dict[str, dict[str, Any]], chosen: list[str]
) -> list[tuple[InformationControl, dict[str, Any]]]:
    controls: list[tuple[InformationControl, dict[str, Any]]] = []
    for control in INFORMATION_CONTROLS:
        if control.scenario not in chosen:
            continue
        scenario = library[control.scenario]
        content = (
            build_control_content(scenario, control)
            if control.built
            else library[control.control]
        )
        differing = build_differing_keys(scenario, content)
        if differing != [control.treatment]:
            raise ValueError(
                f"the control {control.control} of {control.scenario} differs in "
                f"{', '.join(differing)}, not in {control.treatment} only"
            )
        held = build_forecast_shocks(scenario) == build_forecast_shocks(content)
        if control.treatment != "forecasts" and not held:
            raise ValueError(
                f"the control {control.control} of {control.scenario} holds other "
                "demand shocks in its forecasts"
            )
        controls.append((control, content))
    return controls
