#!/usr/bin/env python3
import pytest

from ipfs_datasets_py.web_archiving.web_archive import WebArchive


class TestWebArchiveListArchives:
    """Test WebArchive.list_archives method functionality."""

    @pytest.fixture
    def archive(self):
        """Set up test fixtures."""
        return WebArchive()

    def test_when_calling_list_archives_on_empty_archive_then_returns_empty_list(self, archive):
        """
        Given an empty archive with no archived items.
        When list_archives is called.
        Then an empty list is returned.
        """
        result = archive.list_archives()
        assert result == [], f"Expected empty list but got {result}"

    def test_when_calling_list_archives_on_empty_archive_then_returns_list_type(self, archive):
        """
        Given an empty archive with no archived items.
        When list_archives is called.
        Then the result is of type list.
        """
        result = archive.list_archives()
        assert isinstance(result, list), f"Expected list type but got {type(result)}"

    def test_when_calling_list_archives_with_single_item_then_returns_one_dict(self, archive):
        """
        Given an archive with one archived item.
        When list_archives is called.
        Then a list with one dictionary is returned.
        """
        archive.archive_url("https://example.com")
        result = archive.list_archives()
        assert len(result) == 1, f"Expected 1 item but got {len(result)}"

    def test_when_calling_list_archives_with_single_item_then_dict_has_url_field(self, archive):
        """
        Given an archive with one archived item.
        When list_archives is called.
        Then the dictionary contains a url field.
        """
        archive.archive_url("https://example.com")
        result = archive.list_archives()
        assert "url" in result[0], f"Expected 'url' field but got {list(result[0].keys())}"

    def test_when_calling_list_archives_with_single_item_then_url_matches(self, archive):
        """
        Given an archive with one archived item.
        When list_archives is called.
        Then the url field matches the archived URL.
        """
        test_url = "https://example.com"
        archive.archive_url(test_url)
        result = archive.list_archives()
        assert result[0]["url"] == test_url, f"Expected {test_url} but got {result[0].get('url')}"

    def test_when_calling_list_archives_with_multiple_items_then_returns_multiple_dicts(self, archive):
        """
        Given an archive with multiple archived items.
        When list_archives is called.
        Then a list with multiple dictionaries is returned.
        """
        archive.archive_url("https://example.com")
        archive.archive_url("https://test.org")
        archive.archive_url("https://demo.net")
        result = archive.list_archives()
        assert len(result) == 3, f"Expected 3 items but got {len(result)}"

    def test_when_calling_list_archives_with_multiple_items_then_each_has_url(self, archive):
        """
        Given an archive with multiple archived items.
        When list_archives is called.
        Then each dictionary contains a url field.
        """
        archive.archive_url("https://example.com")
        archive.archive_url("https://test.org")
        result = archive.list_archives()
        assert all("url" in item for item in result), f"Not all items have 'url' field: {result}"

    def test_when_calling_list_archives_with_multiple_items_then_preserves_order(self, archive):
        """
        Given an archive with multiple items added in sequence.
        When list_archives is called.
        Then items appear in insertion order.
        """
        first = "https://first.example.com"
        second = "https://second.example.com"
        archive.archive_url(first)
        archive.archive_url(second)
        result = archive.list_archives()
        urls = [item["url"] for item in result]
        assert urls == [first, second], f"Expected {[first, second]} but got {urls}"

    def test_when_calling_list_archives_with_four_items_then_order_matches_insertion(self, archive):
        """
        Given an archive with four items added in sequence.
        When list_archives is called.
        Then items are returned in insertion order.
        """
        urls = [
            "https://alpha.example.com",
            "https://beta.example.com",
            "https://gamma.example.com",
            "https://delta.example.com"
        ]
        for url in urls:
            archive.archive_url(url)
        result = archive.list_archives()
        returned = [item["url"] for item in result]
        assert returned == urls, f"Expected {urls} but got {returned}"

    def test_when_calling_list_archives_then_first_archived_appears_first(self, archive):
        """
        Given an archive with items added in sequence.
        When list_archives is called.
        Then the first archived item appears first.
        """
        first = "https://first.example.com"
        archive.archive_url(first)
        archive.archive_url("https://second.example.com")
        result = archive.list_archives()
        assert result[0]["url"] == first, f"Expected {first} first but got {result[0]['url']}"

    def test_when_calling_list_archives_then_last_archived_appears_last(self, archive):
        """
        Given an archive with items added in sequence.
        When list_archives is called.
        Then the last archived item appears last.
        """
        last = "https://last.example.com"
        archive.archive_url("https://first.example.com")
        archive.archive_url(last)
        result = archive.list_archives()
        assert result[-1]["url"] == last, f"Expected {last} last but got {result[-1]['url']}"

    def test_when_calling_list_archives_then_item_contains_id(self, archive):
        """
        Given an archive with an archived item.
        When list_archives is called.
        Then the item contains an id field.
        """
        archive.archive_url("https://example.com")
        result = archive.list_archives()
        assert "id" in result[0] or "archive_id" in result[0], f"No id field in {list(result[0].keys())}"

    def test_when_calling_list_archives_then_item_contains_url(self, archive):
        """
        Given an archive with an archived item.
        When list_archives is called.
        Then the item contains a url field.
        """
        archive.archive_url("https://example.com")
        result = archive.list_archives()
        assert "url" in result[0], f"No url field in {list(result[0].keys())}"

    def test_when_calling_list_archives_then_item_contains_timestamp(self, archive):
        """
        Given an archive with an archived item.
        When list_archives is called.
        Then the item contains a timestamp field.
        """
        archive.archive_url("https://example.com")
        result = archive.list_archives()
        assert "timestamp" in result[0], f"No timestamp field in {list(result[0].keys())}"

    def test_when_calling_list_archives_then_item_contains_metadata(self, archive):
        """
        Given an archive with an archived item.
        When list_archives is called.
        Then the item contains a metadata field.
        """
        archive.archive_url("https://example.com", metadata={"test": "data"})
        result = archive.list_archives()
        assert "metadata" in result[0], f"No metadata field in {list(result[0].keys())}"

    def test_when_calling_list_archives_then_item_contains_status(self, archive):
        """
        Given an archive with an archived item.
        When list_archives is called.
        Then the item contains a status field.
        """
        archive.archive_url("https://example.com")
        result = archive.list_archives()
        assert "status" in result[0], f"No status field in {list(result[0].keys())}"

    def test_when_calling_list_archives_multiple_times_then_state_unchanged(self, archive):
        """
        Given an archive with archived items.
        When list_archives is called multiple times.
        Then the internal state remains unchanged.
        """
        archive.archive_url("https://example.com")
        first_call = archive.list_archives()
        second_call = archive.list_archives()
        assert first_call == second_call, f"State changed: {first_call} != {second_call}"

    def test_when_calling_list_archives_multiple_times_then_returns_independent_copies(self, archive):
        """
        Given an archive with archived items.
        When list_archives is called multiple times.
        Then independent list copies are returned.
        """
        archive.archive_url("https://example.com")
        first = archive.list_archives()
        second = archive.list_archives()
        assert first is not second, f"Lists are not independent copies"

    def test_when_modifying_returned_list_then_archive_unaffected(self, archive):
        """
        Given an archive with archived items.
        When the returned list is modified.
        Then the archive internal state is unaffected.
        """
        archive.archive_url("https://example.com")
        result = archive.list_archives()
        result.clear()
        new_result = archive.list_archives()
        assert len(new_result) == 1, f"Archive affected: expected 1 item but got {len(new_result)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])