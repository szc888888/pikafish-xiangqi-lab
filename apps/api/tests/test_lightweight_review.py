import asyncio

import pytest

from app.models import EngineResponse, Score
from app.review import classify_loss, review_game
from app.xiangqi import Position, START_FEN, terminal_status


def test_auth_validation_uses_the_already_parsed_body_instead_of_reading_the_stream():
    from fastapi.exceptions import RequestValidationError
    from starlette.requests import Request
    from app.main import validation_error_response

    async def consumed_stream():
        raise AssertionError('The consumed stream must not be read again')

    request = Request({'type': 'http', 'path': '/auth/email/register', 'headers': []}, receive=consumed_stream)
    error = RequestValidationError([{'loc': ['body', 'accept_privacy'], 'msg': 'Field required', 'type': 'missing'}], body={'email': 'alice@example.com'})
    response = asyncio.run(validation_error_response(request, error))
    assert response.status_code == 422


@pytest.mark.parametrize(('after', 'grade'), [(3, 'blunder'), (-3, 'good')])
def test_review_normalizes_uci_mate_for_the_player_who_moved(after, grade):
    class Engine:
        async def analyze(self, fen, moves, *args):
            if not moves:
                return EngineResponse(bestmove='h2e2', score=Score(type='cp', value=0))
            # Positive UCI mate means the opponent (now to move) can force mate.
            return EngineResponse(bestmove='a6a5', score=Score(type='mate', value=after))

    result = asyncio.run(review_game(Engine(), START_FEN, ['a3a4'], 8, 250, 1, 128))
    assert result.items[0].grade == grade
    assert result.items[0].loss_cp is None


@pytest.mark.parametrize(('fen', 'status'), [
    (START_FEN, None),
    ('4k4/9/4R4/9/9/4P4/9/9/9/4K4 b - - 0 1', None),
    ('R3k4/9/4R4/9/9/4P4/9/9/9/4K4 b - - 0 1', 'checkmate'),
    ('4k4/3R5/5R3/9/9/4P4/9/9/9/4K4 b - - 0 1', 'stalemate'),
])
def test_terminal_fixtures_match_the_frontend_rule_contract(fen, status):
    assert terminal_status(Position.from_fen(fen)) == status


@pytest.mark.parametrize(('before', 'after'), [(-3, -5), (-5, -3)])
def test_already_losing_mate_is_not_called_a_new_blunder(before, after):
    assert classify_loss(Score(type='mate', value=before), Score(type='mate', value=after)) == ('unknown', None)
