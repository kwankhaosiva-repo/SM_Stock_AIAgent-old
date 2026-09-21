import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import llm_providers as lp
from llm_providers import LLMRouter, ProviderError


def _fail(_prompt):
    raise ProviderError('boom')


class TestLLMRouter(unittest.TestCase):
    def test_failover_forwards_same_prompt_and_context(self):
        calls = []

        def bad(prompt):
            calls.append(('a', prompt))
            raise ProviderError('429')

        def good(prompt):
            calls.append(('b', prompt))
            return 'ok'

        router = LLMRouter(order=[])
        router.chain = [('a', bad), ('b', good)]
        out = router.generate('SAME CONTEXT PROMPT')

        self.assertEqual(out, 'ok')
        self.assertEqual(router.last_used, 'b')
        # The exact same prompt + context must reach the second provider.
        self.assertEqual(calls[0][1], calls[1][1])

    def test_all_fail_raises(self):
        router = LLMRouter(order=[])
        router.chain = [('a', _fail)]

        with self.assertRaises(ProviderError):
            router.generate('p')

    def test_empty_chain_raises(self):
        # Patch order to empty so the chain is truly empty regardless of
        # which providers happen to be usable in this environment
        # (e.g. a running local Ollama server satisfies the default chain).
        with patch.object(lp.Config, 'LLM_PROVIDER_ORDER', ''):
            router = LLMRouter(order=[])
            self.assertEqual(router.chain, [])
            with self.assertRaises(ProviderError):
                router.generate('p')

    def test_skips_provider_without_key(self):
        with patch.object(lp.Config, 'GROQ_API_KEY', ''):
            with self.assertRaises(ProviderError):
                lp.call_groq('p')

    def test_retry_then_success_within_provider(self):
        attempts = []

        def flaky(prompt):
            attempts.append(prompt)
            if len(attempts) == 1:
                raise ProviderError('transient')
            return 'recovered'

        router = LLMRouter(order=[])
        router.chain = [('a', flaky)]
        out = router.generate('ctx')
        self.assertEqual(out, 'recovered')
        self.assertEqual(len(attempts), 2)


if __name__ == '__main__':
    unittest.main()
