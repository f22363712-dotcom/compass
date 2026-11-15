"""Tests for Module 2: Streaming Span Quoting & Partial Quote Validation."""
import unittest

from project_compass.fact_engine import (
    StreamingQuoteValidator,
    validate_partial_quote,
)


class StreamingQuoteValidationTests(unittest.TestCase):
    def setUp(self):
        self.source = "The quick brown fox jumps over the lazy dog. Immutable facts require evidence."

    def test_validate_partial_quote_success_chain(self):
        """Streaming consecutive chunks correctly matches and updates next_offset."""
        chunks = ["The quick ", "brown fox ", "jumps over"]
        offset = 0
        accumulated = ""
        for chunk in chunks:
            res = validate_partial_quote(self.source, chunk, offset)
            self.assertTrue(res["valid"])
            self.assertEqual(res["matched"], len(chunk))
            self.assertIsNone(res["reason"])
            offset = res["next_offset"]
            accumulated += chunk

        self.assertEqual(accumulated, self.source[:offset])
        self.assertEqual(offset, len("The quick brown fox jumps over"))

    def test_validate_partial_quote_mismatch(self):
        """Mismatch in the middle of a chunk fails at the first diverging character."""
        res = validate_partial_quote(self.source, "The quick blue fox", 0)
        self.assertFalse(res["valid"])
        # 'The quick b' matches (length 11), 'l' diverges from 'r'
        self.assertEqual(res["matched"], 11)
        self.assertEqual(res["next_offset"], 11)
        self.assertEqual(res["reason"], "mismatch")

    def test_validate_partial_quote_beyond_source_end(self):
        """Chunk extending beyond source text is flagged."""
        start = len(self.source) - 9  # 'evidence.'
        chunk = "evidence. Extra text that exceeds source."
        res = validate_partial_quote(self.source, chunk, start)
        self.assertFalse(res["valid"])
        self.assertEqual(res["matched"], 9)
        self.assertEqual(res["reason"], "beyond_source_end")

    def test_validate_partial_quote_out_of_range_offsets(self):
        """Offset < 0 or > len(source) returns offset_out_of_range."""
        res_neg = validate_partial_quote(self.source, "The", -1)
        self.assertFalse(res_neg["valid"])
        self.assertEqual(res_neg["reason"], "offset_out_of_range")

        res_over = validate_partial_quote(self.source, "The", len(self.source) + 10)
        self.assertFalse(res_over["valid"])
        self.assertEqual(res_over["reason"], "offset_out_of_range")

    def test_validate_partial_quote_type_errors(self):
        """Reject non-string or boolean arguments."""
        with self.assertRaises(TypeError):
            validate_partial_quote(123, "text", 0)
        with self.assertRaises(TypeError):
            validate_partial_quote(self.source, None, 0)
        with self.assertRaises(TypeError):
            validate_partial_quote(self.source, "text", True)

    def test_streaming_quote_validator_stateful_accumulator(self):
        """StreamingQuoteValidator stateful feed and span verification."""
        validator = StreamingQuoteValidator(self.source, start_offset=4)  # starts at 'quick brown'
        # Feed chunks
        r1 = validator.feed_chunk("quick ")
        self.assertTrue(r1["valid"])
        self.assertEqual(r1["span"], (4, 10))

        r2 = validator.feed_chunk("brown fox")
        self.assertTrue(r2["valid"])
        self.assertEqual(r2["span"], (4, 19))
        self.assertEqual(validator.accumulated_quote, "quick brown fox")

        # Verify exact span
        self.assertTrue(validator.verify_exact_span("quick brown fox"))
        self.assertFalse(validator.verify_exact_span("quick brown"))

    def test_streaming_quote_validator_invalid_chunk_locks_state(self):
        """Once an invalid token arrives, validator is locked in invalid state."""
        validator = StreamingQuoteValidator(self.source, start_offset=0)
        validator.feed_chunk("The quick ")
        self.assertTrue(validator.is_valid)

        # Divergent token
        r_err = validator.feed_chunk("green dragon")
        self.assertFalse(r_err["valid"])
        self.assertFalse(validator.is_valid)
        self.assertEqual(r_err["reason"], "mismatch")

        # Subsequent chunk must be rejected immediately
        r_after = validator.feed_chunk("more text")
        self.assertFalse(r_after["valid"])
        self.assertEqual(r_after["reason"], "mismatch")


if __name__ == "__main__":
    unittest.main()
