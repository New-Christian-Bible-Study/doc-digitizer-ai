import sys


def _run() -> int:
    from prompt_based.review_chunk_args import parse_cli_args

    cli = parse_cli_args()
    from prompt_based.review_chunk import main

    return main(cli)


if __name__ == '__main__':
    sys.exit(_run())
