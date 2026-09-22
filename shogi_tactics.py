"""Transparent short tactical annotations, not a full shogi search engine."""
import shogi

# Heuristic pawn units. A capture removes board value and adds demoted hand value.
VALUES={1:1,2:3,3:3,4:5,5:6,6:8,7:10,8:0,9:6,10:6,11:6,12:6,13:11,14:13}
BASE={9:1,10:2,11:3,12:4,13:6,14:7}

def capture_gain(piece_type):
    return VALUES[piece_type]+VALUES[BASE.get(piece_type,piece_type)]

def material(board, side):
    total=0
    for sq in range(81):
        p=board.piece_at(sq)
        if p: total+=VALUES[p.piece_type]*(1 if p.color==side else -1)
    for color in (0,1):
        total+=sum(VALUES[pt]*count for pt,count in board.pieces_in_hand[color].items())*(1 if color==side else -1)
    return total

def swing(board, move):
    victim=board.piece_at(move.to_square)
    gain=capture_gain(victim.piece_type) if victim else 0
    if move.promotion:
        pt=board.piece_at(move.from_square).piece_type
        gain+=VALUES[shogi.PIECE_PROMOTED[pt]]-VALUES[pt]
    return gain

def captures(board, square=None):
    # Filter before costly king-safety validation; drops never capture.
    for m in board.generate_pseudo_legal_moves(pawns_drop=False,lances_drop=False,
            knights_drop=False,silvers_drop=False,golds_drop=False,bishops_drop=False,rooks_drop=False):
        if (square is None or m.to_square==square) and board.piece_at(m.to_square) and board.is_legal(m):
            yield m

def best_reply_gain(board):
    best=0; reply=None
    for m in list(captures(board)):
        gain=swing(board,m)
        board.push(m)
        try: recapture=max((swing(board,r) for r in captures(board,m.to_square)),default=0)
        finally: board.pop()
        if gain-recapture>best: best=gain-recapture;reply=m.usi()
    return {'net_material_gain':best,'capture_move':reply}

def annotate(board, move):
    victim=board.piece_at(move.to_square)
    info={'captured_piece':victim.symbol() if victim else None,
          'capture_material_swing':capture_gain(victim.piece_type) if victim else 0,
          'immediate_material_gain':swing(board,move)}
    board.push(move)
    try:
        info['gives_check']=board.is_check()
        info['checkmate']=board.is_checkmate()
        info['opponent_best_capture_after_recapture']=best_reply_gain(board)
        info['immediate_gain_minus_reply_risk']=info['immediate_material_gain']-info['opponent_best_capture_after_recapture']['net_material_gain']
    finally: board.pop()
    return info
