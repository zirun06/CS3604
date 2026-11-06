import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from openai import BadRequestError, AuthenticationError

from infrastructure.shared.models.text import TextModel


def gateway_error():
    response = httpx.Response(400, request=httpx.Request('POST', 'https://api.arc-bench.com/v1/chat/completions'))
    return BadRequestError('model_proxy_error: connection reset by peer',
                           response=response, body={'code': 'proxy_error'})


class GatewayRecovery(unittest.TestCase):
    def model(self, retries):
        model = TextModel.__new__(TextModel)
        model.client = Mock()
        model.max_output_tokens = 100
        model._token_parameter = 'max_completion_tokens'
        model._reasoning_supported = True
        model.transient_retries = retries
        return model

    def test_wrapped_connection_reset_retries_same_request(self):
        model = self.model(2)
        with (patch('infrastructure.shared.models.text.invoke', side_effect=[gateway_error(), 'ok']) as invoke,
              patch('infrastructure.shared.models.text.time.sleep')):
            self.assertEqual(model._request(model='deepseek-flash', messages=[]), 'ok')
            self.assertEqual(invoke.call_args_list[0], invoke.call_args_list[1])

    def test_retry_budget_is_finite_and_defaults_remain_disabled(self):
        for retries in (0, 2):
            with self.subTest(retries=retries):
                with (patch('infrastructure.shared.models.text.invoke', side_effect=gateway_error()) as invoke,
                      patch('infrastructure.shared.models.text.time.sleep')):
                    with self.assertRaises(BadRequestError):
                        self.model(retries)._request(model='deepseek-flash')
                    self.assertEqual(invoke.call_count, retries + 1)

    def test_auth_and_plain_bad_request_fail_immediately(self):
        request = httpx.Request('POST', 'https://api.arc-bench.com/v1/chat/completions')
        errors = [BadRequestError('unsupported parameter', response=httpx.Response(400, request=request), body={}),
                  AuthenticationError('invalid key', response=httpx.Response(401, request=request), body={})]
        for error in errors:
            with patch('infrastructure.shared.models.text.invoke', side_effect=error) as invoke:
                with self.assertRaises(type(error)):
                    self.model(2)._request(model='deepseek-flash')
                self.assertEqual(invoke.call_count, 1)

    def test_full_file_truncation_requests_complete_sources(self):
        model = self.model(0)
        model.name, model.reasoning, model.json_mode = 'deepseek-flash', 'none', True
        model._request = Mock(return_value=SimpleNamespace(choices=[SimpleNamespace(finish_reason='length')]))
        with self.assertRaises(ValueError) as result:
            model.generate_json('Return {"files":{"frontend/src/App.tsx":"complete TSX"}}', {})
        self.assertIn('including every requested path', str(result.exception))
        self.assertNotIn('omit unchanged files', str(result.exception))


if __name__ == '__main__':
    unittest.main()
