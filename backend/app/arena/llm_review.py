"""Compatibility entry point: review with message-mode providers, off the call path."""
from app.arena.review_llm import request_review


def _request_review(candidate):
    return request_review({'caller_text':candidate['caller_text'],
        'requested_action':candidate['requested_action'],'detected_intent':candidate['detected_intent'],
        'player_text':candidate['user_text_masked']})


def analyze_session_candidates(session_id):
    from app.arena.data_review import analyze_session
    analyze_session(session_id)
