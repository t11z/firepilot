# firepilot.rego — FirePilot CI/CD Gate 2: OPA Policy Validation
#
# Package: firepilot.validate
#
# All policies in this file evaluate the structured input assembled by the
# CI/CD pipeline (build-opa-input.py) for a single folder/position directory.
# The pipeline deserializes YAML to JSON before passing to OPA — policies
# operate on JSON objects, not raw YAML text.
#
# Input schema:
# {
#   "manifest": {
#     "schema_version": 1,
#     "folder": "shared",
#     "position": "pre",
#     "rule_order": ["allow-web-to-app", "allow-app-to-db"]
#   },
#   "rule_files": {
#     "allow-web-to-app": { /* deserialized content of allow-web-to-app.yaml */ },
#     "allow-app-to-db":  { /* deserialized content of allow-app-to-db.yaml */  }
#   },
#   "directory": {
#     "folder":   "Shared",   /* actual parent directory name from filesystem */
#     "position": "pre"       /* actual directory name (pre or post) */
#   }
# }
#
# Usage:
#   opa eval -i input.json -d firepilot.rego 'data.firepilot.validate.deny'
#
# A passing run produces an empty set: {"result": [{"expressions": [{"value": []}]}]}
# Any non-empty deny set means the configuration is invalid and must be fixed.

package firepilot.validate

import future.keywords.if
import future.keywords.in

# ---------------------------------------------------------------------------
# Helper: firepilot_managed_tag_present
#
# Returns true if the rule's tag array contains the mandatory scope marker.
# ---------------------------------------------------------------------------
firepilot_managed_tag_present(rule) if {
    "firepilot-managed" in rule.tag
}

# ---------------------------------------------------------------------------
# Policy: firepilot_managed_tag_required
#
# Every rule file must include "firepilot-managed" in its tag array.
# This tag is the scope boundary between FirePilot-managed rules and rules
# managed by other means (ADR-0007). CI/CD enforces its presence so that
# the deployment pipeline can tag rules correctly in SCM and drift detection
# can identify rules under FirePilot's scope.
# ---------------------------------------------------------------------------
deny[msg] if {
    some filename
    rule := input.rule_files[filename]
    not firepilot_managed_tag_present(rule)
    msg := sprintf("Rule '%s' is missing required tag 'firepilot-managed'", [rule.name])
}

# ---------------------------------------------------------------------------
# Policy: manifest_entries_have_files
#
# Every entry in _rulebase.yaml rule_order must have a corresponding
# {name}.yaml file in the same directory. A manifest entry without a file
# is a dangling reference — it would cause deployment to fail attempting to
# read a nonexistent configuration (ADR-0007 invariant 1).
# ---------------------------------------------------------------------------
deny[msg] if {
    entry := input.manifest.rule_order[_]
    not input.rule_files[entry]
    msg := sprintf("Manifest references rule '%s' but no corresponding YAML file exists", [entry])
}

# ---------------------------------------------------------------------------
# Policy: rule_files_in_manifest
#
# Every {name}.yaml file present in the directory must appear in rule_order.
# A file without a manifest entry is silently ignored by the deployment
# pipeline — this policy makes such omissions a hard failure (ADR-0007
# invariant 2).
# ---------------------------------------------------------------------------
deny[msg] if {
    some name
    _ = input.rule_files[name]
    not manifest_contains(name)
    msg := sprintf("Rule file '%s.yaml' exists but is not listed in _rulebase.yaml rule_order", [name])
}

# Helper: manifest_contains checks whether a name appears in rule_order.
manifest_contains(name) if {
    name == input.manifest.rule_order[_]
}

# ---------------------------------------------------------------------------
# Policy: name_matches_filename
#
# The name field inside the rule YAML must equal the filename (without .yaml).
# This invariant ensures that the SCM rule name matches the Git filename and
# prevents silent misidentification during drift detection (ADR-0007).
# ---------------------------------------------------------------------------
deny[msg] if {
    some filename
    rule := input.rule_files[filename]
    rule.name != filename
    msg := sprintf(
        "Rule file '%s.yaml' has name field '%s' which does not match the filename",
        [filename, rule.name],
    )
}

# ---------------------------------------------------------------------------
# Policy: folder_matches_directory
#
# The manifest's folder field must equal the actual parent directory name
# supplied by the pipeline. Prevents a _rulebase.yaml from being copied into
# the wrong folder without updating the folder field (ADR-0007 invariant 4).
# ---------------------------------------------------------------------------
deny[msg] if {
    input.manifest.folder != input.directory.folder
    msg := sprintf(
        "Manifest folder '%s' does not match directory folder '%s'",
        [input.manifest.folder, input.directory.folder],
    )
}

# ---------------------------------------------------------------------------
# Policy: position_matches_directory
#
# The manifest's position field must equal the actual directory name (pre or
# post) supplied by the pipeline. Prevents a manifest from being placed in
# the wrong position directory (ADR-0007 invariant 5).
# ---------------------------------------------------------------------------
deny[msg] if {
    input.manifest.position != input.directory.position
    msg := sprintf(
        "Manifest position '%s' does not match directory position '%s'",
        [input.manifest.position, input.directory.position],
    )
}

# ---------------------------------------------------------------------------
# Policy: no_forbidden_fields
#
# Rule files must NOT contain 'id', 'folder', or 'position'. These fields
# are derived from directory structure ('folder', 'position') or assigned by
# SCM at creation time ('id'). Their presence in a rule file indicates a
# rule was incorrectly authored or copied from an API response (ADR-0007).
# Defense-in-depth: additionalProperties: false in the JSON Schema is Gate 1;
# this OPA policy is Gate 2.
# ---------------------------------------------------------------------------
deny[msg] if {
    some filename
    rule := input.rule_files[filename]
    "id" in object.keys(rule)
    msg := sprintf("Rule file '%s.yaml' contains forbidden field 'id'", [filename])
}

deny[msg] if {
    some filename
    rule := input.rule_files[filename]
    "folder" in object.keys(rule)
    msg := sprintf("Rule file '%s.yaml' contains forbidden field 'folder'", [filename])
}

deny[msg] if {
    some filename
    rule := input.rule_files[filename]
    "position" in object.keys(rule)
    msg := sprintf("Rule file '%s.yaml' contains forbidden field 'position'", [filename])
}

# ---------------------------------------------------------------------------
# Policy: no_duplicate_rule_order
#
# rule_order must not contain duplicate entries. Duplicates would cause a
# rule to be deployed twice in sequence — a silent misconfiguration in the
# first-match rulebase model. Defense-in-depth: 'uniqueItems: true' in the
# JSON Schema is Gate 1; this OPA policy is Gate 2.
# ---------------------------------------------------------------------------
deny[msg] if {
    rule_order := input.manifest.rule_order
    count(rule_order) != count({entry | entry := rule_order[_]})
    msg := "Manifest rule_order contains duplicate entries"
}

# ===========================================================================
# Zone Topology Policies (ADR-0008)
#
# All policies below are conditional on input.zone_mapping being present.
# When build-opa-input.py is invoked without --zones, zone_mapping is absent
# and none of these policies fire — preserving backward compatibility with
# rule directories validated before zones.yaml was introduced.
# ===========================================================================

# ---------------------------------------------------------------------------
# Helper: zone_role
#
# Returns the architectural role string for a zone name by looking it up in
# the zone mapping. Undefined (fails) if the zone name is not in zone_mapping,
# which prevents topology policies from producing spurious deny messages for
# zones that failed zone_reference_valid.
# ---------------------------------------------------------------------------
zone_role(zone_name) := input.zone_mapping[zone_name].role

# ---------------------------------------------------------------------------
# Policy: zone_reference_valid
#
# Every zone referenced in a rule file's from or to field must exist as a
# key in input.zone_mapping. The literal value "any" is exempt. This catches
# typos and references to zones not yet registered in zones.yaml before the
# configuration reaches the dry-run gate (ADR-0008).
# ---------------------------------------------------------------------------
deny[msg] if {
    input.zone_mapping
    some filename
    rule := input.rule_files[filename]
    zone := rule.from[_]
    zone != "any"
    not input.zone_mapping[zone]
    msg := sprintf("Rule '%s' references unknown source zone '%s'", [filename, zone])
}

deny[msg] if {
    input.zone_mapping
    some filename
    rule := input.rule_files[filename]
    zone := rule.to[_]
    zone != "any"
    not input.zone_mapping[zone]
    msg := sprintf("Rule '%s' references unknown destination zone '%s'", [filename, zone])
}

# ---------------------------------------------------------------------------
# Policy: no_internet_to_database
#
# No allow rule may have a source zone with role "internet" and a destination
# zone with role "database". Direct internet-to-database traffic bypasses all
# intermediate tiers and violates network segmentation principles (ADR-0008).
# ---------------------------------------------------------------------------
deny[msg] if {
    input.zone_mapping
    some filename
    rule := input.rule_files[filename]
    rule.action == "allow"
    src_zone := rule.from[_]
    zone_role(src_zone) == "internet"
    dst_zone := rule.to[_]
    zone_role(dst_zone) == "database"
    msg := sprintf(
        "Rule '%s' permits direct traffic from internet zone to database zone",
        [filename],
    )
}

# ---------------------------------------------------------------------------
# Policy: no_internet_to_management
#
# No allow rule may have a source zone with role "internet" and a destination
# zone with role "management". Exposing management networks directly to the
# internet is a critical security boundary violation (ADR-0008).
# ---------------------------------------------------------------------------
deny[msg] if {
    input.zone_mapping
    some filename
    rule := input.rule_files[filename]
    rule.action == "allow"
    src_zone := rule.from[_]
    zone_role(src_zone) == "internet"
    dst_zone := rule.to[_]
    zone_role(dst_zone) == "management"
    msg := sprintf(
        "Rule '%s' permits direct traffic from internet zone to management zone",
        [filename],
    )
}

# ---------------------------------------------------------------------------
# Policy: no_overly_permissive_internet_rule
#
# No allow rule may combine a source zone with role "internet" with both
# source: ["any"] and destination: ["any"]. This pattern permits all internet
# traffic to all destinations — the broadest possible allow rule from an
# untrusted zone (ADR-0008).
# ---------------------------------------------------------------------------
deny[msg] if {
    input.zone_mapping
    some filename
    rule := input.rule_files[filename]
    rule.action == "allow"
    src_zone := rule.from[_]
    zone_role(src_zone) == "internet"
    "any" in rule.source
    "any" in rule.destination
    msg := sprintf(
        "Rule '%s' is overly permissive: internet source zone with source 'any' and destination 'any'",
        [filename],
    )
}
