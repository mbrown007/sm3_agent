"""
Tests for Knowledge Base (KB) parsing and matching functionality.

Covers:
- _parse_kb_entry: Parsing structured KB text files
- _load_kb_entries: Loading and caching KB entries from disk
- _match_kb_entries: Matching alerts to relevant KB articles
- Helper functions: _tokenize, _normalize_text
"""
import pytest
from pathlib import Path
from typing import List
from unittest.mock import patch, MagicMock

from backend.api.alerts import (
    _parse_kb_entry,
    _load_kb_entries,
    _match_kb_entries,
    _tokenize,
    _normalize_text,
    KnowledgeBaseEntry,
    KB_CACHE,
)


class TestTokenize:
    """Test the _tokenize helper function."""
    
    def test_basic_tokenization(self):
        """Should extract alphanumeric tokens 3+ chars, excluding stopwords."""
        result = _tokenize("LSP not registered on gateway")
        assert "lsp" in result
        assert "registered" in result
        assert "gateway" in result
        assert "not" in result  # 'not' is 3 chars, will be included
        assert "on" not in result  # Too short
    
    def test_removes_stopwords(self):
        """Should filter out common stopwords."""
        result = _tokenize("alert critical error on server host")
        # All these are in _STOPWORDS
        assert "alert" not in result
        assert "critical" not in result
        assert "error" not in result
        assert "server" not in result
        assert "host" not in result
    
    def test_handles_special_characters(self):
        """Should extract tokens despite special characters."""
        result = _tokenize("postgres-replication-lag > 100ms")
        assert "postgres" in result
        assert "replication" in result
        assert "lag" in result
        assert "100ms" in result
    
    def test_case_insensitive(self):
        """Should normalize to lowercase."""
        result = _tokenize("PostgreSQL Database")
        assert "postgresql" in result
        assert "database" in result
        assert "PostgreSQL" not in result
    
    def test_empty_string(self):
        """Should return empty list for empty input."""
        assert _tokenize("") == []
    
    def test_min_length_filter(self):
        """Should only include tokens 3+ characters."""
        result = _tokenize("ab abc abcd")
        assert "ab" not in result  # Too short
        assert "abc" in result
        assert "abcd" in result


class TestNormalizeText:
    """Test the _normalize_text helper function."""
    
    def test_lowercase_conversion(self):
        """Should convert to lowercase."""
        assert _normalize_text("LSP Not Registered") == "lsp not registered"
    
    def test_removes_special_chars(self):
        """Should replace non-alphanumeric with spaces."""
        assert _normalize_text("postgres-replication-lag") == "postgres replication lag"
    
    def test_normalizes_whitespace(self):
        """Should collapse multiple spaces to single space."""
        assert _normalize_text("LSP   not    registered") == "lsp not registered"
    
    def test_strips_edges(self):
        """Should strip leading/trailing whitespace."""
        assert _normalize_text("  LSP not registered  ") == "lsp not registered"
    
    def test_empty_string(self):
        """Should handle empty string."""
        assert _normalize_text("") == ""


class TestParseKBEntry:
    """Test KB entry parsing from text files."""
    
    def test_parse_simple_entry(self):
        """Should parse a simple KB entry with basic fields."""
        content = """Alert Name: LSP Not Registered
Category: Avaya
Description: LSP endpoint is not showing as registered
Impact: Phones cannot make calls
Possible Cause: Network connectivity issue
Possible Cause: Avaya CM service down
Next Steps: Check network connectivity
Next Steps: Restart Avaya CM service
"""
        entry = _parse_kb_entry(content, "lsp-not-registered.txt")
        
        assert entry.title == "Alert Name: LSP Not Registered"
        assert entry.source_file == "lsp-not-registered.txt"
        assert entry.alert_name == "LSP Not Registered"
        assert entry.category == "Avaya"
        assert entry.description == "LSP endpoint is not showing as registered"
        assert entry.impact == "Phones cannot make calls"
        assert len(entry.possible_causes) == 2
        assert "Network connectivity issue" in entry.possible_causes
        assert "Avaya CM service down" in entry.possible_causes
        assert len(entry.next_steps) == 2
        assert "Check network connectivity" in entry.next_steps
    
    def test_parse_with_alert_expression(self):
        """Should parse alert expression field."""
        content = """Alert Name: High Replication Lag
Alert Expression: pg_replication_lag > 100
Category: PostgreSQL
Description: Replication lag exceeds threshold
"""
        entry = _parse_kb_entry(content, "pg-repl-lag.txt")
        
        assert entry.alert_name == "High Replication Lag"
        assert entry.alert_expression == "pg_replication_lag > 100"
        assert entry.category == "PostgreSQL"
    
    def test_parse_multiline_sections(self):
        """Should handle multiline content in sections."""
        content = """Alert Name: SSH Probe Failing
Description: SSH connectivity check is failing
This could indicate the host is down or SSH service is unavailable
Possible Cause: Host is powered off
Possible Cause: SSH daemon is not running
Possible Cause: Firewall blocking port 22
Next Steps: Ping the host to check if it's online
If ping succeeds, check SSH service status
"""
        entry = _parse_kb_entry(content, "ssh-probe.txt")
        
        # Description should combine multiline content
        assert "connectivity check is failing" in entry.description
        assert "host is down" in entry.description
        assert len(entry.possible_causes) == 3
        assert len(entry.next_steps) >= 1
    
    def test_parse_with_parentheses_in_headers(self):
        """Should handle headers with parentheses (e.g., 'Impact (System)')."""
        content = """Alert Name: Database Down
Category (Type): PostgreSQL
Impact (System): All services unavailable
"""
        entry = _parse_kb_entry(content, "db-down.txt")
        
        # Parentheses should be stripped from header matching
        assert entry.alert_name == "Database Down"
        assert entry.category == "PostgreSQL"
        assert entry.impact == "All services unavailable"
    
    def test_parse_extra_notes(self):
        """Should parse extra notes section."""
        content = """Alert Name: Test Alert
Extra Notes: This is a known intermittent issue
Extra Notes: Check vendor knowledge base article KB-12345
"""
        entry = _parse_kb_entry(content, "test.txt")
        
        assert len(entry.extra_notes) == 2
        assert "known intermittent issue" in entry.extra_notes[0]
        assert "KB-12345" in entry.extra_notes[1]
    
    def test_parse_with_missing_fields(self):
        """Should handle entries with missing optional fields."""
        content = """Alert Name: Simple Alert
Category: Test
"""
        entry = _parse_kb_entry(content, "simple.txt")
        
        assert entry.alert_name == "Simple Alert"
        assert entry.category == "Test"
        assert entry.description is None
        assert entry.impact is None
        assert entry.possible_causes == []
        assert entry.next_steps == []
    
    def test_parse_empty_content(self):
        """Should handle empty content gracefully."""
        entry = _parse_kb_entry("", "empty.txt")
        
        # Should use filename as fallback title
        assert entry.source_file == "empty.txt"
        assert entry.title == "empty.txt"
    
    def test_keywords_extracted_from_content(self):
        """Should extract keywords from alert name, description, etc."""
        content = """Alert Name: PostgreSQL Replication Lag
Category: Database
Description: PostgreSQL replication lag exceeds threshold
Impact: Data synchronization delayed
"""
        entry = _parse_kb_entry(content, "pg-lag.txt")
        
        # Should have keywords from alert name, description, etc.
        assert len(entry.keywords) > 0
        assert "postgresql" in entry.keywords
        assert "replication" in entry.keywords
        assert "lag" in entry.keywords
        # Stopwords should be filtered
        assert "alert" not in entry.keywords
    
    def test_keywords_sorted_and_unique(self):
        """Should return sorted unique keywords."""
        content = """Alert Name: Test Test Alert
Description: Test description with test keyword
"""
        entry = _parse_kb_entry(content, "test.txt")
        
        # "test" appears multiple times but should be unique
        test_count = entry.keywords.count("test")
        assert test_count <= 1
        # Should be sorted
        assert entry.keywords == sorted(entry.keywords)


class TestLoadKBEntries:
    """Test loading KB entries from disk with caching."""
    
    def setup_method(self):
        """Reset KB cache before each test."""
        KB_CACHE["entries"] = []
        KB_CACHE["files"] = {}
    
    @patch("backend.api.alerts._get_kb_dir")
    def test_load_no_files(self, mock_get_kb_dir):
        """Should return empty list when no KB files exist."""
        mock_kb_dir = MagicMock(spec=Path)
        mock_kb_dir.glob.return_value = []
        mock_get_kb_dir.return_value = mock_kb_dir
        
        entries = _load_kb_entries()
        
        assert entries == []
    
    @patch("backend.api.alerts._get_kb_dir")
    def test_load_single_file(self, mock_get_kb_dir):
        """Should load a single KB file."""
        mock_file = MagicMock(spec=Path)
        mock_file.name = "test.txt"
        mock_file.read_text.return_value = """Alert Name: Test Alert
Category: Test"""
        mock_file.stat.return_value.st_mtime = 123456.0
        
        mock_kb_dir = MagicMock(spec=Path)
        mock_kb_dir.glob.return_value = [mock_file]
        mock_get_kb_dir.return_value = mock_kb_dir
        
        entries = _load_kb_entries()
        
        assert len(entries) == 1
        assert entries[0].alert_name == "Test Alert"
        assert entries[0].source_file == "test.txt"
    
    @patch("backend.api.alerts._get_kb_dir")
    def test_load_multiple_files(self, mock_get_kb_dir):
        """Should load multiple KB files."""
        mock_file1 = MagicMock(spec=Path)
        mock_file1.name = "alert1.txt"
        mock_file1.read_text.return_value = "Alert Name: Alert 1"
        mock_file1.stat.return_value.st_mtime = 123456.0
        
        mock_file2 = MagicMock(spec=Path)
        mock_file2.name = "alert2.txt"
        mock_file2.read_text.return_value = "Alert Name: Alert 2"
        mock_file2.stat.return_value.st_mtime = 123457.0
        
        mock_kb_dir = MagicMock(spec=Path)
        mock_kb_dir.glob.return_value = [mock_file1, mock_file2]
        mock_get_kb_dir.return_value = mock_kb_dir
        
        entries = _load_kb_entries()
        
        assert len(entries) == 2
        alert_names = {e.alert_name for e in entries}
        assert "Alert 1" in alert_names
        assert "Alert 2" in alert_names
    
    @patch("backend.api.alerts._get_kb_dir")
    def test_caching_same_files(self, mock_get_kb_dir):
        """Should use cache when files haven't changed."""
        mock_file = MagicMock(spec=Path)
        mock_file.name = "test.txt"
        mock_file.read_text.return_value = "Alert Name: Test"
        mock_file.stat.return_value.st_mtime = 123456.0
        
        mock_kb_dir = MagicMock(spec=Path)
        mock_kb_dir.glob.return_value = [mock_file]
        mock_get_kb_dir.return_value = mock_kb_dir
        
        # First load
        entries1 = _load_kb_entries()
        call_count_1 = mock_file.read_text.call_count
        
        # Second load (should use cache)
        entries2 = _load_kb_entries()
        call_count_2 = mock_file.read_text.call_count
        
        assert entries1 == entries2
        # read_text should not be called again (cached)
        assert call_count_1 == call_count_2
    
    @patch("backend.api.alerts._get_kb_dir")
    def test_cache_invalidation_on_file_change(self, mock_get_kb_dir):
        """Should reload when file modification time changes."""
        mock_file = MagicMock(spec=Path)
        mock_file.name = "test.txt"
        mock_file.read_text.return_value = "Alert Name: Test"
        
        # First load with old mtime
        mock_file.stat.return_value.st_mtime = 123456.0
        mock_kb_dir = MagicMock(spec=Path)
        mock_kb_dir.glob.return_value = [mock_file]
        mock_get_kb_dir.return_value = mock_kb_dir
        
        entries1 = _load_kb_entries()
        
        # Simulate file modification
        mock_file.stat.return_value.st_mtime = 999999.0
        
        # Should reload
        entries2 = _load_kb_entries()
        
        # read_text should be called again
        assert mock_file.read_text.call_count == 2
    
    @patch("backend.api.alerts._get_kb_dir")
    def test_handles_read_errors(self, mock_get_kb_dir, caplog):
        """Should log warning and continue when file read fails."""
        mock_file1 = MagicMock(spec=Path)
        mock_file1.name = "good.txt"
        mock_file1.read_text.return_value = "Alert Name: Good"
        mock_file1.stat.return_value.st_mtime = 123456.0
        
        mock_file2 = MagicMock(spec=Path)
        mock_file2.name = "bad.txt"
        mock_file2.read_text.side_effect = PermissionError("Access denied")
        mock_file2.stat.return_value.st_mtime = 123457.0
        
        mock_kb_dir = MagicMock(spec=Path)
        mock_kb_dir.glob.return_value = [mock_file1, mock_file2]
        mock_get_kb_dir.return_value = mock_kb_dir
        
        entries = _load_kb_entries()
        
        # Should load the good file despite error on bad file
        assert len(entries) == 1
        assert entries[0].alert_name == "Good"


class TestMatchKBEntries:
    """Test matching alerts to KB entries."""
    
    def test_exact_alert_name_match(self):
        """Should score highest for exact alert name match."""
        entries = [
            KnowledgeBaseEntry(
                title="LSP Alert",
                source_file="lsp.txt",
                alert_name="LSP Not Registered",
                keywords=["lsp", "registered"]
            ),
            KnowledgeBaseEntry(
                title="Other Alert",
                source_file="other.txt",
                alert_name="Different Alert",
                keywords=["different"]
            )
        ]
        
        matches = _match_kb_entries(
            alert_name="LSP Not Registered",
            labels={},
            annotations={},
            entries=entries,
            limit=3
        )
        
        assert len(matches) == 1
        assert matches[0]["entry"].alert_name == "LSP Not Registered"
        assert matches[0]["score"] >= 3.0  # Exact match bonus
    
    def test_partial_alert_name_match(self):
        """Should match when alert name contains KB alert name."""
        entries = [
            KnowledgeBaseEntry(
                title="Replication",
                source_file="repl.txt",
                alert_name="Replication Lag",
                keywords=["replication", "lag"]
            )
        ]
        
        matches = _match_kb_entries(
            alert_name="PostgreSQL Replication Lag High",
            labels={},
            annotations={},
            entries=entries,
            limit=3
        )
        
        assert len(matches) == 1
        assert matches[0]["entry"].alert_name == "Replication Lag"
    
    def test_keyword_matching(self):
        """Should match when alert name triggers +3.0 score (substring match)."""
        entries = [
            KnowledgeBaseEntry(
                title="SSH Probe",
                source_file="ssh.txt",
                alert_name="SSH Probe Failing",  # Will match as substring
                description="SSH probe connectivity failing blackbox monitoring",
                keywords=["ssh", "probe", "connectivity", "failing", "blackbox", "monitoring", "network"]
            )
        ]

        matches = _match_kb_entries(
            alert_name="Blackbox SSH Probe Failing",  # Contains "SSH Probe Failing"
            labels={"job": "blackbox-ssh"},
            annotations={"description": "SSH connection failed"},
            entries=entries,
            limit=3
        )

        # Should match due to alert name substring match (+3.0 score)
        assert len(matches) >= 1
        # Should have matched on keywords: ssh, probe, connectivity
        assert len(matches[0]["matched_terms"]) > 0
    
    def test_score_threshold_filtering(self):
        """Should filter out entries below score threshold."""
        entries = [
            KnowledgeBaseEntry(
                title="High Score",
                source_file="high.txt",
                alert_name="LSP Not Registered",
                keywords=["lsp", "registered"]
            ),
            KnowledgeBaseEntry(
                title="Low Score",
                source_file="low.txt",
                alert_name="Unrelated Alert",
                keywords=["unrelated", "different"]
            )
        ]
        
        matches = _match_kb_entries(
            alert_name="LSP Not Registered",
            labels={},
            annotations={},
            entries=entries,
            limit=10
        )
        
        # Only high-scoring entry should match (score >= 2.0)
        assert len(matches) == 1
        assert matches[0]["entry"].alert_name == "LSP Not Registered"
    
    def test_limit_results(self):
        """Should limit number of results returned."""
        entries = [
            KnowledgeBaseEntry(
                title=f"Entry {i}",
                source_file=f"entry{i}.txt",
                alert_name="Test Alert",
                keywords=["test", "alert"]
            )
            for i in range(10)
        ]
        
        matches = _match_kb_entries(
            alert_name="Test Alert",
            labels={},
            annotations={},
            entries=entries,
            limit=3
        )
        
        assert len(matches) == 3
    
    def test_sorts_by_score_descending(self):
        """Should return matches sorted by score (highest first)."""
        entries = [
            KnowledgeBaseEntry(
                title="Partial Match",
                source_file="partial.txt",
                alert_name="Similar Alert Name Here",
                keywords=["similar", "alert", "name", "here"]
            ),
            KnowledgeBaseEntry(
                title="Exact Match",
                source_file="exact.txt",
                alert_name="Test Alert",  # Exact match gets +3.0 score
                keywords=["test", "alert", "exact", "match"]
            )
        ]

        matches = _match_kb_entries(
            alert_name="Test Alert",
            labels={},
            annotations={},
            entries=entries,
            limit=10
        )

        # Exact match should be first (higher score)
        assert len(matches) >= 1
        assert matches[0]["entry"].alert_name == "Test Alert"
        if len(matches) > 1:
            assert matches[0]["score"] > matches[1]["score"]
    
    def test_empty_entries_list(self):
        """Should return empty list when given no KB entries."""
        matches = _match_kb_entries(
            alert_name="Test",
            labels={},
            annotations={},
            entries=[],
            limit=3
        )
        
        assert matches == []
    
    def test_uses_labels_and_annotations_for_matching(self):
        """Should search across labels and annotations for keywords."""
        entries = [
            KnowledgeBaseEntry(
                title="PostgreSQL Replication",
                source_file="pg.txt",
                alert_name="PostgreSQL Replication Lag",  # Exact match
                keywords=["postgres", "postgresql", "database", "replication", "lag", "primary"]
            )
        ]

        matches = _match_kb_entries(
            alert_name="postgresql replication lag",  # Exact match (case insensitive)
            labels={"instance": "postgres-primary"},
            annotations={"summary": "PostgreSQL replication issue"},
            entries=entries,
            limit=3
        )

        # Should match based on exact alert name match (+3.0 score)
        assert len(matches) >= 1
        assert "postgres" in matches[0]["matched_terms"] or "postgresql" in matches[0]["matched_terms"]
    
    def test_matched_terms_returned(self):
        """Should include list of matched terms in results."""
        entries = [
            KnowledgeBaseEntry(
                title="SSH Connectivity",
                source_file="ssh.txt",
                alert_name="SSH Connectivity Check",  # Exact match
                keywords=["ssh", "probe", "connectivity", "check", "network"]
            )
        ]

        matches = _match_kb_entries(
            alert_name="SSH Connectivity Check",  # Exact match
            labels={"job": "ssh-monitoring"},
            annotations={},
            entries=entries,
            limit=3
        )

        assert len(matches) >= 1
        # Matched terms should be populated from keyword overlap
        assert "matched_terms" in matches[0]
        assert isinstance(matches[0]["matched_terms"], list)
    
    def test_none_alert_name_handled(self):
        """Should handle None alert_name gracefully."""
        entries = [
            KnowledgeBaseEntry(
                title="Test",
                source_file="test.txt",
                alert_name="Test",
                keywords=["test"]
            )
        ]
        
        # Should not crash with None alert_name
        matches = _match_kb_entries(
            alert_name=None,
            labels={"key": "value"},
            annotations={},
            entries=entries,
            limit=3
        )
        
        # May or may not match, but should not raise exception
        assert isinstance(matches, list)
