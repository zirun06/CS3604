"""Exercise the platform command line and its exit contract."""

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import main


class CompilerCLI(unittest.TestCase):
    def source(self, root):
        source = root / 'input'
        source.mkdir()
        (source / 'requirements.yaml').write_text('id: ROOT\nchildren: []\n')
        return source

    def test_main_initializes_the_compiler_with_positional_requirement_path(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root)
            output = root / 'output'
            with patch.object(main, 'Compiler') as cls:
                main.main([str(source), '--output-dir', str(output), '--model-log'])
            cls.assert_called_once_with(source.resolve(), output.resolve(), model_log=True, port=3000, pause=False)
            cls.return_value.compile.assert_called_once_with(stage=None, from_stage=None)
            self.assertFalse(output.exists())
            args = main.parse_args([str(source), '--output-dir', str(output)])
            self.assertEqual(args.requirement_path, source.resolve())
            self.assertEqual(args.output_dir, output.resolve())
            self.assertFalse(args.model_log)
            self.assertTrue(main.parse_args([str(source), '--output-dir', str(output), '--debug-model-io']).model_log)

    def test_requirement_path_and_output_are_required_with_exact_option_names(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root)
            for arguments in ([], [str(source)], ['-o', str(root/'output')],
                    ['--input', str(source), '-o', str(root/'output')],
                    [str(source), '--output', str(root/'output')]):
                with self.subTest(arguments=arguments), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                    main.parse_args(arguments)

    def test_port_and_short_output_option_reach_the_compiler(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root)
            with patch.object(main, 'Compiler') as cls:
                main.main([str(source), '-o', str(root / 'output'), '--port', '33042'])
            self.assertEqual(cls.call_args.kwargs['port'], 33042)
            for port in ('0', '-1', '65536'):
                with self.subTest(port=port), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                    main.parse_args([str(source), '-o', str(root / 'output'), '--port', port])

    def test_invalid_locations_fail_before_creating_compiler_or_output(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root)
            empty = root / 'empty'
            empty.mkdir()
            output_file = root / 'file'
            output_file.write_text('preserve')
            for inputs, output in [(root / 'missing', root / 'output'), (empty, root / 'output'),
                    (source, source), (source, source / 'nested'), (source, output_file)]:
                with self.subTest(inputs=inputs, output=output), patch.object(main, 'Compiler') as cls, redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        main.main([str(inputs), '--output-dir', str(output)])
                    self.assertEqual(error.exception.code, 2)
                    cls.assert_not_called()
            self.assertFalse((root / 'output').exists())
            self.assertEqual(output_file.read_text(), 'preserve')

    def test_failure_and_interrupt_exit_without_starting_another_compilation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root)
            for failure, status in [(ValueError('failed test acceptance'), 0), (KeyboardInterrupt(), 130)]:
                with self.subTest(status=status), patch.object(main, 'Compiler') as cls, redirect_stderr(StringIO()):
                    cls.return_value.current_stage = '08_implement_backend_tdd.py'
                    cls.return_value.compile.side_effect = failure
                    with self.assertRaises(SystemExit) as error:
                        main.main([str(source), '--output-dir', str(root / 'output')])
                    self.assertEqual(error.exception.code, status)
                    cls.return_value.compile.assert_called_once_with(stage=None, from_stage=None)


if __name__ == '__main__':
    unittest.main()
