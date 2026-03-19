# firepilot_test.rego — OPA Test Suite for firepilot.validate policies
#
# Run with: opa test ci/policies/ -v
#
# Each test constructs its own input inline — no dependency on external
# fixture files. This makes the test suite self-contained and runnable
# without filesystem access to the YAML fixtures.
#
# Pattern for all tests that check deny message content:
#   msgs := deny with input as { ... }
#   msgs["expected deny message"]         # set membership via bracket notation
#
# Note: `x in msgs` does not work for sets produced by partial rules evaluated
# with `with input as` in OPA 0.70.0. Use `msgs[x]` (bracket notation) instead,
# which correctly checks set/object membership via the OPA unification mechanism.

package firepilot.validate

import future.keywords.if

# ---------------------------------------------------------------------------
# Shared helpers: reusable rule definitions used across multiple tests.
# ---------------------------------------------------------------------------

# Constructs a minimal valid rule object for use in test inputs.
_valid_rule(name) := {
    "schema_version": 1,
    "name": name,
    "from": ["web-zone"],
    "to": ["app-zone"],
    "source": ["any"],
    "source_user": ["any"],
    "destination": ["any"],
    "service": ["application-default"],
    "application": ["any"],
    "category": ["any"],
    "action": "allow",
    "tag": ["firepilot-managed"],
    "log_end": true,
}

# ---------------------------------------------------------------------------
# test_valid_config_no_deny
#
# A fully valid configuration with two rules and a matching manifest.
# Must produce zero deny messages.
# ---------------------------------------------------------------------------
test_valid_config_no_deny if {
    msgs := deny with input as {
        "manifest": {
            "schema_version": 1,
            "folder": "Shared",
            "position": "pre",
            "rule_order": ["allow-web-to-app", "allow-app-to-db"],
        },
        "rule_files": {
            "allow-web-to-app": {
                "schema_version": 1,
                "name": "allow-web-to-app",
                "description": "Permit HTTPS traffic from web zone to application zone",
                "from": ["web-zone"],
                "to": ["app-zone"],
                "source": ["web-subnet-10.1.0.0-24"],
                "negate_source": false,
                "source_user": ["any"],
                "destination": ["app-subnet-10.2.0.0-24"],
                "negate_destination": false,
                "service": ["application-default"],
                "application": ["ssl", "web-browsing"],
                "category": ["any"],
                "action": "allow",
                "tag": ["firepilot-managed", "app:customer-portal"],
                "profile_setting": {"group": ["best-practice"]},
                "log_setting": "default-log-profile",
                "log_start": false,
                "log_end": true,
            },
            "allow-app-to-db": {
                "schema_version": 1,
                "name": "allow-app-to-db",
                "description": "Permit database traffic from application zone to database zone",
                "from": ["app-zone"],
                "to": ["db-zone"],
                "source": ["app-subnet-10.2.0.0-24"],
                "source_user": ["any"],
                "destination": ["db-subnet-10.3.0.0-24"],
                "service": ["application-default"],
                "application": ["mysql", "postgresql"],
                "category": ["any"],
                "action": "allow",
                "tag": ["firepilot-managed", "app:customer-portal"],
                "log_end": true,
            },
        },
        "directory": {"folder": "Shared", "position": "pre"},
    }
    count(msgs) == 0
}

# ---------------------------------------------------------------------------
# test_missing_firepilot_tag
#
# A rule whose tag array does not contain "firepilot-managed" must produce
# a deny message naming the rule.
# ---------------------------------------------------------------------------
test_missing_firepilot_tag if {
    msgs := deny with input as {
        "manifest": {
            "schema_version": 1,
            "folder": "Shared",
            "position": "pre",
            "rule_order": ["bad-rule"],
        },
        "rule_files": {
            "bad-rule": {
                "schema_version": 1,
                "name": "bad-rule",
                "from": ["web-zone"],
                "to": ["app-zone"],
                "source": ["any"],
                "source_user": ["any"],
                "destination": ["any"],
                "service": ["application-default"],
                "application": ["any"],
                "category": ["any"],
                "action": "allow",
                # tag array present but missing "firepilot-managed"
                "tag": ["team:network-ops"],
            },
        },
        "directory": {"folder": "Shared", "position": "pre"},
    }
    msgs["Rule 'bad-rule' is missing required tag 'firepilot-managed'"]
}

# ---------------------------------------------------------------------------
# test_orphan_rule_file
#
# A rule file that exists but is not listed in rule_order must produce a deny.
# (bidirectional consistency: files must appear in the manifest)
# ---------------------------------------------------------------------------
test_orphan_rule_file if {
    msgs := deny with input as {
        "manifest": {
            "schema_version": 1,
            "folder": "Shared",
            "position": "pre",
            # rule_order only lists listed-rule; orphan-rule is intentionally absent
            "rule_order": ["listed-rule"],
        },
        "rule_files": {
            "listed-rule": _valid_rule("listed-rule"),
            # orphan-rule exists as a file but is not in rule_order
            "orphan-rule": _valid_rule("orphan-rule"),
        },
        "directory": {"folder": "Shared", "position": "pre"},
    }
    msgs["Rule file 'orphan-rule.yaml' exists but is not listed in _rulebase.yaml rule_order"]
}

# ---------------------------------------------------------------------------
# test_missing_rule_file
#
# A manifest entry that references a nonexistent rule file must produce a deny.
# (bidirectional consistency: manifest entries must have corresponding files)
# ---------------------------------------------------------------------------
test_missing_rule_file if {
    msgs := deny with input as {
        "manifest": {
            "schema_version": 1,
            "folder": "Shared",
            "position": "pre",
            # nonexistent-rule is in rule_order but has no corresponding file
            "rule_order": ["existing-rule", "nonexistent-rule"],
        },
        "rule_files": {
            # only existing-rule has a file; nonexistent-rule does not
            "existing-rule": _valid_rule("existing-rule"),
        },
        "directory": {"folder": "Shared", "position": "pre"},
    }
    msgs["Manifest references rule 'nonexistent-rule' but no corresponding YAML file exists"]
}

# ---------------------------------------------------------------------------
# test_name_mismatch
#
# A rule whose name field does not match the filename (key in rule_files)
# must produce a deny message.
# ---------------------------------------------------------------------------
test_name_mismatch if {
    msgs := deny with input as {
        "manifest": {
            "schema_version": 1,
            "folder": "Shared",
            "position": "pre",
            "rule_order": ["some-rule"],
        },
        "rule_files": {
            # file is keyed as "some-rule" but name field says "other-rule"
            "some-rule": {
                "schema_version": 1,
                "name": "other-rule",
                "from": ["web-zone"],
                "to": ["app-zone"],
                "source": ["any"],
                "source_user": ["any"],
                "destination": ["any"],
                "service": ["application-default"],
                "application": ["any"],
                "category": ["any"],
                "action": "allow",
                "tag": ["firepilot-managed"],
            },
        },
        "directory": {"folder": "Shared", "position": "pre"},
    }
    msgs["Rule file 'some-rule.yaml' has name field 'other-rule' which does not match the filename"]
}

# ---------------------------------------------------------------------------
# test_folder_mismatch
#
# A manifest whose folder field does not match the actual parent directory
# name must produce a deny message.
# ---------------------------------------------------------------------------
test_folder_mismatch if {
    msgs := deny with input as {
        "manifest": {
            "schema_version": 1,
            # manifest says folder is "Shared"
            "folder": "Shared",
            "position": "pre",
            "rule_order": ["some-rule"],
        },
        "rule_files": {"some-rule": _valid_rule("some-rule")},
        "directory": {
            # but the actual directory says folder is "Production"
            "folder": "Production",
            "position": "pre",
        },
    }
    msgs["Manifest folder 'Shared' does not match directory folder 'Production'"]
}

# ---------------------------------------------------------------------------
# test_position_mismatch
#
# A manifest whose position field does not match the actual directory name
# must produce a deny message.
# ---------------------------------------------------------------------------
test_position_mismatch if {
    msgs := deny with input as {
        "manifest": {
            "schema_version": 1,
            "folder": "Shared",
            # manifest says position is "pre"
            "position": "pre",
            "rule_order": ["some-rule"],
        },
        "rule_files": {"some-rule": _valid_rule("some-rule")},
        "directory": {
            "folder": "Shared",
            # but the actual directory says position is "post"
            "position": "post",
        },
    }
    msgs["Manifest position 'pre' does not match directory position 'post'"]
}

# ---------------------------------------------------------------------------
# test_forbidden_field_id
#
# A rule containing the 'id' field (SCM-assigned UUID, must not appear in
# rule files) must produce a deny message.
# ---------------------------------------------------------------------------
test_forbidden_field_id if {
    msgs := deny with input as {
        "manifest": {
            "schema_version": 1,
            "folder": "Shared",
            "position": "pre",
            "rule_order": ["bad-rule"],
        },
        "rule_files": {
            "bad-rule": {
                "schema_version": 1,
                "name": "bad-rule",
                # 'id' is forbidden — assigned by SCM, must not appear in rule files
                "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "from": ["web-zone"],
                "to": ["app-zone"],
                "source": ["any"],
                "source_user": ["any"],
                "destination": ["any"],
                "service": ["application-default"],
                "application": ["any"],
                "category": ["any"],
                "action": "allow",
                "tag": ["firepilot-managed"],
            },
        },
        "directory": {"folder": "Shared", "position": "pre"},
    }
    msgs["Rule file 'bad-rule.yaml' contains forbidden field 'id'"]
}

# ---------------------------------------------------------------------------
# test_forbidden_field_folder
#
# A rule containing the 'folder' field (derived from directory structure,
# must not appear in rule files) must produce a deny message.
# ---------------------------------------------------------------------------
test_forbidden_field_folder if {
    msgs := deny with input as {
        "manifest": {
            "schema_version": 1,
            "folder": "Shared",
            "position": "pre",
            "rule_order": ["bad-rule"],
        },
        "rule_files": {
            "bad-rule": {
                "schema_version": 1,
                "name": "bad-rule",
                # 'folder' is forbidden — derived from directory structure
                "folder": "Shared",
                "from": ["web-zone"],
                "to": ["app-zone"],
                "source": ["any"],
                "source_user": ["any"],
                "destination": ["any"],
                "service": ["application-default"],
                "application": ["any"],
                "category": ["any"],
                "action": "allow",
                "tag": ["firepilot-managed"],
            },
        },
        "directory": {"folder": "Shared", "position": "pre"},
    }
    msgs["Rule file 'bad-rule.yaml' contains forbidden field 'folder'"]
}

# ---------------------------------------------------------------------------
# test_forbidden_field_position
#
# A rule containing the 'position' field (derived from directory structure,
# must not appear in rule files) must produce a deny message.
# ---------------------------------------------------------------------------
test_forbidden_field_position if {
    msgs := deny with input as {
        "manifest": {
            "schema_version": 1,
            "folder": "Shared",
            "position": "pre",
            "rule_order": ["bad-rule"],
        },
        "rule_files": {
            "bad-rule": {
                "schema_version": 1,
                "name": "bad-rule",
                # 'position' is forbidden — derived from directory structure
                "position": "pre",
                "from": ["web-zone"],
                "to": ["app-zone"],
                "source": ["any"],
                "source_user": ["any"],
                "destination": ["any"],
                "service": ["application-default"],
                "application": ["any"],
                "category": ["any"],
                "action": "allow",
                "tag": ["firepilot-managed"],
            },
        },
        "directory": {"folder": "Shared", "position": "pre"},
    }
    msgs["Rule file 'bad-rule.yaml' contains forbidden field 'position'"]
}

# ---------------------------------------------------------------------------
# test_duplicate_rule_order
#
# A manifest rule_order containing duplicate entries must produce a deny
# message. (Defense-in-depth: JSON Schema uniqueItems is Gate 1; this is
# Gate 2.)
# ---------------------------------------------------------------------------
test_duplicate_rule_order if {
    msgs := deny with input as {
        "manifest": {
            "schema_version": 1,
            "folder": "Shared",
            "position": "pre",
            # allow-web-to-app appears twice — duplicate
            "rule_order": ["allow-web-to-app", "allow-app-to-db", "allow-web-to-app"],
        },
        "rule_files": {
            "allow-web-to-app": {
                "schema_version": 1,
                "name": "allow-web-to-app",
                "from": ["web-zone"],
                "to": ["app-zone"],
                "source": ["any"],
                "source_user": ["any"],
                "destination": ["any"],
                "service": ["application-default"],
                "application": ["any"],
                "category": ["any"],
                "action": "allow",
                "tag": ["firepilot-managed"],
                "log_end": true,
            },
            "allow-app-to-db": {
                "schema_version": 1,
                "name": "allow-app-to-db",
                "from": ["app-zone"],
                "to": ["db-zone"],
                "source": ["any"],
                "source_user": ["any"],
                "destination": ["any"],
                "service": ["application-default"],
                "application": ["any"],
                "category": ["any"],
                "action": "allow",
                "tag": ["firepilot-managed"],
                "log_end": true,
            },
        },
        "directory": {"folder": "Shared", "position": "pre"},
    }
    msgs["Manifest rule_order contains duplicate entries"]
}
