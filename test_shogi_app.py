import tempfile
import unittest
from pathlib import Path
import shogi
from shogi_app import Game
from shogi_tactics import annotate, best_reply_gain, capture_gain, material

class ShogiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.g=Game();self.g.folder=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_click_and_undo(self):
        g=self.g
        g.square(shogi.SQUARE_NAMES.index('7g'))
        g.square(shogi.SQUARE_NAMES.index('7f'))
        self.assertEqual(g.moves,['7g7f'])
        self.assertFalse(g.play(shogi.Move.from_usi('7f7e')))
        g.play(shogi.Move.from_usi('3c3d'));g.undo()
        self.assertEqual(g.board.sfen(),shogi.Board().sfen())
    def test_promotion_drop_and_checkmate(self):
        g=self.g
        for usi in ['7g7f','3c3d']: self.assertTrue(g.play(shogi.Move.from_usi(usi)))
        g.square(shogi.SQUARE_NAMES.index('8h'));g.square(shogi.SQUARE_NAMES.index('2b'))
        self.assertEqual({m.promotion for m in g.promotion},{True,False})
        for usi in ['8h2b+','4a5b','B*4b','5a4a','2b3a']:
            self.assertTrue(g.play(shogi.Move.from_usi(usi)))
        self.assertEqual(g.result,'あなたの勝ち')
    def test_double_pawn_drop_forbidden(self):
        g=self.g;g.board.pieces_in_hand[0][shogi.PAWN]=1
        g.selected=('hand',shogi.PAWN)
        self.assertEqual(g.options(),[])

    def test_annotation_finds_mate_and_preserves_position(self):
        b=shogi.Board()
        for m in ['7g7f','3c3d','8h2b+','4a5b','B*4b','5a4a']: b.push_usi(m)
        before=b.sfen();history=list(b.move_stack)
        facts=annotate(b,shogi.Move.from_usi('2b3a'))
        self.assertTrue(facts['checkmate']);self.assertTrue(facts['gives_check'])
        self.assertEqual(b.sfen(),before);self.assertEqual(list(b.move_stack),history)

    def test_capture_values_include_demoted_hand_piece(self):
        self.assertEqual(capture_gain(shogi.PAWN),2)
        self.assertEqual(capture_gain(shogi.PROM_PAWN),7)
        b=shogi.Board();self.assertEqual(material(b,0),0)
        b.pieces_in_hand[0][shogi.ROOK]=1
        self.assertEqual(material(b,0),10)

    def test_reply_discount_for_legal_recapture(self):
        b=shogi.Board();b.clear()
        def put(square,pt,color): b.set_piece_at(shogi.SQUARE_NAMES.index(square),shogi.Piece(pt,color))
        put('9i',shogi.KING,0);put('1a',shogi.KING,1)
        put('5c',shogi.ROOK,1);put('5e',shogi.PAWN,0);b.turn=1
        self.assertEqual(best_reply_gain(b)['net_material_gain'],2)
        put('5h',shogi.ROOK,0)
        before=b.sfen()
        self.assertEqual(best_reply_gain(b)['net_material_gain'],0)
        self.assertEqual(b.sfen(),before)

if __name__=='__main__':unittest.main()
