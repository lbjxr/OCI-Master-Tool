import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from oci_master.services import billing


class CliErrorHandlingTests(unittest.TestCase):
    def test_billing_cli_returns_fixed_error_with_error_code(self):
        output = StringIO()
        with patch.object(billing, "get_oci_config", side_effect=RuntimeError("secret-token-url")):
            with redirect_stdout(output):
                billing.export_usage_fee({})
        text = output.getvalue()
        self.assertIn("错误编号", text)
        self.assertNotIn("secret-token-url", text)


if __name__ == "__main__":
    unittest.main()
