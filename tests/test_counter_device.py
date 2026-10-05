"""Three-key paid crafting, cancellation, stale requests and item recovery."""
import unittest
import test_device_controls as base

demo, controls = base.demo, base.controls


class CounterDeviceContracts(unittest.TestCase):
    setUp = base.DeviceControlsContracts.setUp
    input = base.DeviceControlsContracts.input
    click = base.DeviceControlsContracts.click
    long = base.DeviceControlsContracts.long
    device = base.DeviceControlsContracts.device

    def choose(self, label):
        for _ in range(40):
            labels = [row['label'] for row in self.device.rows()]
            target = next((i for i, value in enumerate(labels) if label in value), None)
            self.assertIsNotNone(target, (label, self.device.page, labels))
            if self.device.selected == target:
                return self.click('C')
            self.click('B' if self.device.selected < target else 'A')
        self.fail((label, self.device.page, self.device.selected, labels))

    def start(self):
        self.choose('战术远征'); self.choose('主搭档'); self.choose('喷火龙')
        self.choose('出发'); self.choose('确认')
        session = demo.SESSIONS[self.device.sid]
        session.player.inventory.add_component('band')
        session.player.inventory.add_component('charcoal')
        demo.api_action({'cmd': 'save', 'sid': session.sid})
        self.input('state')
        return session

    def test_craft_cancel_equip_sell_and_duplicate_release(self):
        session = self.start()
        self.choose('仓库与教学'); self.choose('组件'); self.choose('封疗针')
        seq = self.device.sequence
        self.click('C')  # Default cancel.
        self.assertEqual(self.device.sequence, seq)
        self.assertEqual(session.player.inventory.total_components(), 2)
        self.choose('封疗针'); self.choose('确认')
        self.assertEqual(session.player.inventory.total_components(), 0)
        self.assertEqual(session.player.inventory.finished, ['healing_needle'])
        seq = self.device.sequence
        self.input('up', 'C'); self.input('tick')
        self.assertEqual(self.device.sequence, seq)
        self.choose('仓库与教学'); self.choose('成品装备'); self.choose('封疗针')
        self.choose('小火龙'); self.choose('确认')
        self.assertEqual(session.player.grid[(0, 2)].item, 'healing_needle')
        self.choose('棋盘与备战'); self.choose('战场第一行'); self.choose('小火龙')
        self.choose('卸下装备')
        self.assertEqual(session.player.inventory.finished, ['healing_needle'])
        self.assertIsNone(session.player.grid[(0, 2)].item)
        self.choose('保存 / 返回'); self.choose('返回主页')
        demo.SESSIONS.clear()
        self.choose('继续存档')
        self.assertEqual(demo.SESSIONS[self.device.sid].player.inventory.finished, ['healing_needle'])

    def test_stale_craft_confirmation_rejects_without_second_spend(self):
        session = self.start()
        self.choose('仓库与教学'); self.choose('组件'); self.choose('封疗针')
        self.assertEqual(self.device.page, 'confirm')
        self.assertTrue(demo.api_action({'cmd': 'craft', 'sid': session.sid, 'item': 'healing_needle'})['ok'])
        self.input('state')  # The new sequence invalidates the old dialog.
        self.assertEqual(self.device.page, 'prep')
        self.assertEqual(session.player.inventory.finished, ['healing_needle'])
        self.assertEqual(session.player.inventory.total_components(), 0)


if __name__ == '__main__':
    unittest.main()
