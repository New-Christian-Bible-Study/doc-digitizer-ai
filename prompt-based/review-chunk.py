import sys

# Thin CLI entry: ``python review-chunk.py`` → ``prompt_based.review_chunk.main``.


def _run() -> int:
    from prompt_based.review_chunk_args import parse_cli_args

    cli = parse_cli_args()
    from prompt_based.review_chunk import main

    return main(cli)


if __name__ == '__main__':
    sys.exit(_run())
