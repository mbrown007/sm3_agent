"""
Tests for knowledge base matching accuracy.

Verifies that alert names are correctly matched to runbook entries
using text similarity scoring.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.api.alerts import _search_knowledge_base, KnowledgeBaseEntry


@pytest.mark.unit
def test_exact_alert_name_match(temp_dir, sample_kb_entry):
    """Test exact match between alert name and KB file."""
    # Create KB file with exact alert name
    kb_dir = temp_dir / "kb"
    kb_dir.mkdir()
    kb_file = kb_dir / "High Error Rate Investigation.txt"
    kb_file.write_text(sample_kb_entry)
    
    with patch("backend.api.alerts.KB_DIR", kb_dir):
        matches = _search_knowledge_base(
            "High Error Rate Investigation",
            score_threshold=2.0
        )
    
    assert len(matches) == 1
    assert matches[0].title == "High Error Rate Investigation"
    assert matches[0].score >= 2.0
    assert "HighErrorRate" in " ".join(matches[0].matched_terms)


@pytest.mark.unit
def test_partial_keyword_match(temp_dir, sample_kb_entry):
    """Test partial keyword matching."""
    kb_dir = temp_dir / "kb"
    kb_dir.mkdir()
    kb_file = kb_dir / "Database Connection Issues.txt"
    kb_file.write_text(sample_kb_entry)
    
    with patch("backend.api.alerts.KB_DIR", kb_dir):
        matches = _search_knowledge_base(
            "DatabaseConnectionPoolExhausted",
            score_threshold=1.0
        )
    
    assert len(matches) >= 1
    assert any("database" in m.title.lower() for m in matches)


@pytest.mark.unit
def test_no_match_scenario(temp_dir):
    """Test when no KB entries match the alert."""
    kb_dir = temp_dir / "kb"
    kb_dir.mkdir()
    kb_file = kb_dir / "Unrelated Issue.txt"
    kb_file.write_text("This is about something completely different.")
    
    with patch("backend.api.alerts.KB_DIR", kb_dir):
        matches = _search_knowledge_base(
            "CompletelyDifferentAlert",
            score_threshold=2.0
        )
    
    # Should return empty list when no good matches
    assert len(matches) == 0 or matches[0].score < 2.0


@pytest.mark.unit
def test_multiple_kb_files(temp_dir):
    """Test matching with multiple KB files."""
    kb_dir = temp_dir / "kb"
    kb_dir.mkdir()
    
    # Create multiple KB files
    (kb_dir / "API Error Rate.txt").write_text("# API Error Rate\n\nHigh error rate...")
    (kb_dir / "Database Latency.txt").write_text("# Database Latency\n\nSlow queries...")
    (kb_dir / "Network Issues.txt").write_text("# Network Issues\n\nConnection problems...")
    
    with patch("backend.api.alerts.KB_DIR", kb_dir):
        matches = _search_knowledge_base("API Error", score_threshold=1.0)
    
    # Should match API-related KB
    assert len(matches) > 0
    assert any("API" in m.title for m in matches)


@pytest.mark.unit
def test_score_threshold_filtering(temp_dir, sample_kb_entry):
    """Test that score threshold correctly filters results."""
    kb_dir = temp_dir / "kb"
    kb_dir.mkdir()
    kb_file = kb_dir / "Error Rate.txt"
    kb_file.write_text(sample_kb_entry)
    
    with patch("backend.api.alerts.KB_DIR", kb_dir):
        # Low threshold - should match
        matches_low = _search_knowledge_base("Error", score_threshold=0.5)
        
        # High threshold - may not match
        matches_high = _search_knowledge_base("Error", score_threshold=10.0)
    
    assert len(matches_low) >= len(matches_high)


@pytest.mark.unit
def test_empty_kb_directory(temp_dir):
    """Test behavior with empty KB directory."""
    kb_dir = temp_dir / "kb"
    kb_dir.mkdir()
    
    with patch("backend.api.alerts.KB_DIR", kb_dir):
        matches = _search_knowledge_base("SomeAlert", score_threshold=2.0)
    
    assert matches == []


@pytest.mark.unit  
def test_matched_terms_extraction(temp_dir):
    """Test that matched terms are correctly extracted."""
    kb_dir = temp_dir / "kb"
    kb_dir.mkdir()
    content = """# Database Connection Pool
    
    When database connection pool is exhausted, the application
    cannot process requests properly.
    """
    (kb_dir / "Database Pool.txt").write_text(content)
    
    with patch("backend.api.alerts.KB_DIR", kb_dir):
        matches = _search_knowledge_base(
            "DatabaseConnectionPoolExhausted",
            score_threshold=0.5
        )
    
    if matches:
        # Verify some relevant terms were matched
        all_terms = " ".join(matches[0].matched_terms).lower()
        assert any(term in all_terms for term in ["database", "connection", "pool"])
