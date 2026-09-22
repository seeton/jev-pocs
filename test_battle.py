import unittest
from battle import Battle, baseline_orders, basic_orders
from tactical_policy import tactical_orders
import copy


class BattleTests(unittest.TestCase):
    def test_roles_and_cooldowns(self):
        b = Battle()
        tank, archer, mage, healer = b.units[:4]
        self.assertIn('taunt', b.options(tank))
        self.assertIn('attack:boss', b.options(archer))
        self.assertIn('stealth',b.options(archer))
        self.assertIn('retreat:boss',b.options(archer))
        self.assertIn('aoe:boss', b.options(mage))
        self.assertIn('buff:tank', b.options(mage))
        self.assertIn('debuff:boss', b.options(mage))
        self.assertNotIn('heal:tank',b.options(healer))
        self.assertIn('barrier:tank',b.options(healer))
        tank.hp -= 70
        self.assertIn('heal:tank', b.options(healer))
        b.apply({'healer': 'heal:tank'})
        b.tick(1/30)
        self.assertAlmostEqual(tank.hp, 200)
        self.assertNotIn('heal:tank',b.options(healer))
        self.assertIn('barrier:tank',b.options(healer))

    def test_aoe_single_target_and_effects(self):
        b = Battle()
        mage, archer, tank = b.by_id['mage'], b.by_id['archer'], b.by_id['tank']
        enemies = b.living('enemy')
        for enemy in enemies:
            enemy.x, enemy.y = 200, 250
        before = [e.hp for e in enemies]
        mage.order = 'aoe:boss'; b.cast(mage)
        self.assertEqual([h-e.hp for h,e in zip(before,enemies)], [22]*5)
        before = [e.hp for e in enemies]
        archer.order = 'attack:boss'; b.cast(archer)
        self.assertEqual([h-e.hp for h,e in zip(before,enemies)], [20,0,0,0,0])
        mage.order = 'buff:archer'; b.cast(mage)
        before_hp = enemies[0].hp
        archer.order = 'attack:boss'; b.cast(archer)
        self.assertEqual(before_hp-enemies[0].hp,30)
        mage.order = 'debuff:boss'; b.cast(mage)
        tank.guard = 4
        b.damage(enemies[0],tank,10)
        self.assertAlmostEqual(tank.hp,240-10*.55*.4)

    def test_invalid_or_dead_target_is_not_accepted(self):
        b = Battle()
        b.by_id['boss'].hp = 0
        self.assertEqual(b.apply({'archer':'attack:boss', 'healer':'attack:minion1'}),0)
        b.by_id['archer'].hp = 0
        self.assertEqual(b.apply({'archer':'attack:minion1'}),0)

    def test_taunt_and_finite_battle(self):
        b = Battle()
        b.apply({'tank':'taunt'})
        b.tick(1/30)
        self.assertTrue(all(e.target=='tank' for e in b.living('enemy')))
        for frame in range(90*30):
            if frame%15 == 0:
                _, options = b.snapshot()
                b.apply(basic_orders(b,options))
            b.tick(1/30)
            if b.result:
                break
        self.assertIn(b.result,('VICTORY','DEFEAT'))
        self.assertTrue(all(0 <= u.hp <= u.max_hp for u in b.units))

    def test_tactical_policy_uses_legal_choices_without_mutating_observation(self):
        b = Battle()
        used = set()
        for frame in range(90*30):
            if frame % 15 == 0:
                state, options = b.snapshot()
                before = copy.deepcopy((state, options))
                orders = tactical_orders(state, options)
                self.assertEqual((state, options), before)
                self.assertEqual(orders, tactical_orders(state, options))
                for hero, order in orders.items():
                    self.assertIn(order, options[hero])
                    used.add(order.split(':')[0])
                b.apply(orders)
            b.tick(1/30)
            if b.result: break
        self.assertTrue({'interrupt', 'cover', 'retreat', 'barrier'} <= used, used)
        self.assertTrue(all(0 <= u.hp <= u.max_hp for u in b.units))

    def test_tactical_archer_evades_committed_lethal_hit(self):
        b = Battle()
        b.by_id['archer'].hp = 20
        b.by_id['boss'].windup = 1
        b.by_id['boss'].windup_target = 'archer'
        state, choices = b.snapshot()
        self.assertEqual(tactical_orders(state, choices)['archer'], 'stealth')

    def test_backline_priority_and_taunt_reuse(self):
        b = Battle()
        b.tick(1/30)
        self.assertEqual(b.by_id['boss'].target, 'healer')
        self.assertEqual(b.by_id['minion1'].target, 'mage')
        self.assertEqual(b.by_id['minion2'].target, 'archer')
        b.apply({'tank':'taunt'})
        b.tick(1/30)
        self.assertTrue(all(e.target == 'tank' for e in b.living('enemy')))
        for _ in range(65):
            b.tick(1/30)
        self.assertEqual(b.by_id['tank'].taunt, 0)
        self.assertGreater(b.by_id['tank'].taunt_cooldown, 7)
        self.assertNotIn('taunt', b.options(b.by_id['tank']))
        self.assertEqual(b.by_id['boss'].target, 'healer')
        self.assertEqual(b.apply({'tank':'taunt'}), 0)
        # Even a pending/stale order cannot bypass the separate skill cooldown.
        b.by_id['tank'].order = 'taunt'
        b.tick(1/30)
        self.assertEqual(b.by_id['tank'].taunt, 0)
        for _ in range(240):
            b.tick(1/30)
        self.assertIn('taunt', b.options(b.by_id['tank']))

    def test_stealth_evades_committed_hit_but_stops_own_attacks(self):
        b=Battle(); archer=b.by_id['archer']; boss=b.by_id['boss']
        boss.x,boss.y=archer.x+45,archer.y
        boss.windup=0.3; boss.windup_target=archer.id
        archer.cooldown=1
        self.assertEqual(b.apply({'archer':'stealth'}),1)
        self.assertEqual(b.options(archer),{})
        self.assertNotEqual(b.enemy_target(boss,b.living('party')).id,'archer')
        for _ in range(12): b.tick(1/30)
        self.assertEqual(archer.hp,archer.max_hp)
        self.assertEqual(b.apply({'archer':'attack:boss'}),0)
        self.assertGreater(archer.skill_cooldowns['stealth'],9)

    def test_interrupt_works_during_normal_cooldown_and_requires_windup(self):
        b=Battle(); tank=b.by_id['tank']; boss=b.by_id['boss']
        boss.x,boss.y=tank.x+180,tank.y
        boss.windup=1; boss.windup_target='healer'; tank.cooldown=1
        self.assertEqual(b.apply({'tank':'interrupt:boss'}),1)
        self.assertEqual(boss.windup,0)
        self.assertGreater(boss.stun,0)
        self.assertEqual(b.interrupts,1)
        boss.windup=1
        self.assertEqual(b.apply({'tank':'interrupt:boss'}),0)
        tank.skill_cooldowns['interrupt']=0; boss.windup=0
        self.assertEqual(b.apply({'tank':'interrupt:boss'}),0)

    def test_cover_and_barrier_split_and_absorb_damage(self):
        b=Battle(); tank=b.by_id['tank']; archer=b.by_id['archer']; healer=b.by_id['healer']
        tank.cooldown=1; healer.cooldown=1
        self.assertEqual(b.apply({'tank':'cover:archer','healer':'barrier:archer'}),2)
        tank.guard=2
        b.damage(b.by_id['boss'],archer,100)
        self.assertAlmostEqual(tank.hp,240-28)
        self.assertEqual(archer.hp,90)
        self.assertEqual(archer.shield,15)
        self.assertEqual(b.absorbed_damage,30)
        self.assertEqual(b.redirected_damage,70)

    def test_retreat_root_and_rescue_have_costs_and_targeted_effects(self):
        b=Battle(); archer=b.by_id['archer']; boss=b.by_id['boss']; mage=b.by_id['mage']; healer=b.by_id['healer']
        archer.x=500; boss.x=600; archer.y=boss.y=285
        archer.order='retreat:boss'; b.cast(archer)
        self.assertAlmostEqual(archer.x,390)
        self.assertEqual(boss.hp,boss.max_hp-12)
        self.assertGreater(archer.skill_cooldowns['retreat'],0)
        mage.order='root:boss'; b.cast(mage)
        old_position=boss.pos
        self.assertFalse(b.move(boss,healer,50,1))
        self.assertEqual(boss.pos,old_position)
        archer.hp=20; healer.order='rescue:archer'; b.cast(healer)
        self.assertEqual(archer.hp,75)
        self.assertEqual(healer.cooldown,3)
        self.assertEqual(healer.skill_cooldowns['rescue'],8)


if __name__=='__main__':
    unittest.main()
