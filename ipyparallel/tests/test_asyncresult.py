"""Tests for asyncresult.py"""
# Copyright (c) IPython Development Team.
# Distributed under the terms of the Modified BSD License.
import os
import time
from datetime import datetime

from IPython.utils.io import capture_output

import ipyparallel as ipp
from .clienttest import ClusterTestCase
from .clienttest import raises_remote
from ipyparallel import error


def wait(n):
    import time

    time.sleep(n)
    return n


def echo(x):
    return x


class AsyncResultTest(ClusterTestCase):
    def test_single_result_view(self):
        """various one-target views get the right value for single_result"""
        eid = self.client.ids[-1]
        ar = self.client[eid].apply_async(lambda: 42)
        self.assertEqual(ar.get(), 42)
        ar = self.client[[eid]].apply_async(lambda: 42)
        self.assertEqual(ar.get(), [42])
        ar = self.client[-1:].apply_async(lambda: 42)
        self.assertEqual(ar.get(), [42])

    def test_get_after_done(self):
        ar = self.client[-1].apply_async(lambda: 42)
        ar.wait()
        self.assertTrue(ar.ready())
        self.assertEqual(ar.get(), 42)
        self.assertEqual(ar.get(), 42)

    def test_get_before_done(self):
        ar = self.client[-1].apply_async(wait, 0.1)
        self.assertRaises(TimeoutError, ar.get, 0)
        ar.wait(0)
        self.assertFalse(ar.ready())
        self.assertEqual(ar.get(), 0.1)

    def test_get_after_error(self):
        ar = self.client[-1].apply_async(lambda: 1 / 0)
        ar.wait(10)
        self.assertRaisesRemote(ZeroDivisionError, ar.get)
        self.assertRaisesRemote(ZeroDivisionError, ar.get)
        self.assertRaisesRemote(ZeroDivisionError, ar.get_dict)

    def test_get_dict(self):
        n = len(self.client)
        ar = self.client[:].apply_async(lambda: 5)
        self.assertEqual(ar.get(), [5] * n)
        d = ar.get_dict()
        self.assertEqual(sorted(d.keys()), sorted(self.client.ids))
        for eid, r in d.items():
            self.assertEqual(r, 5)

    def test_get_dict_single(self):
        view = self.client[-1]
        for v in (list(range(5)), 5, ('abc', 'def'), 'string'):
            ar = view.apply_async(echo, v)
            self.assertEqual(ar.get(), v)
            d = ar.get_dict()
            self.assertEqual(d, {view.targets: v})

    def test_get_dict_bad(self):
        v = self.client.load_balanced_view()
        amr = v.map_async(lambda x: x, range(len(self.client) * 2))
        self.assertRaises(ValueError, amr.get_dict)

    def test_iter_amr(self):
        ar = self.client.load_balanced_view().map_async(wait, [0.125] * 5)
        for r in ar:
            self.assertEqual(r, 0.125)

    def test_iter_multi_result_ar(self):
        ar = self.client[:].apply(wait, 0.125)
        for r in ar:
            self.assertEqual(r, 0.125)

    def test_iter_error(self):
        amr = self.client[:].map_async(lambda x: 1 / (x - 2), range(5))
        # iterating through failing AMR should raise RemoteError
        self.assertRaisesRemote(ZeroDivisionError, list, amr)
        # so should get
        self.assertRaisesRemote(ZeroDivisionError, amr.get)
        amr.wait(10)
        # test iteration again after everything is local
        self.assertRaisesRemote(ZeroDivisionError, list, amr)

    def test_getattr(self):
        ar = self.client[:].apply_async(wait, 0.5)
        self.assertEqual(ar.completed, [None] * len(ar))
        self.assertRaises(AttributeError, lambda: ar._foo)
        self.assertRaises(AttributeError, lambda: ar.__length_hint__())
        self.assertRaises(AttributeError, lambda: ar.foo)
        self.assertFalse(hasattr(ar, '__length_hint__'))
        self.assertFalse(hasattr(ar, 'foo'))
        self.assertTrue(hasattr(ar, 'engine_id'))
        ar.get(5)
        self.assertRaises(AttributeError, lambda: ar._foo)
        self.assertRaises(AttributeError, lambda: ar.__length_hint__())
        self.assertRaises(AttributeError, lambda: ar.foo)
        self.assertTrue(isinstance(ar.engine_id, list))
        self.assertEqual(ar.engine_id, ar['engine_id'])
        self.assertFalse(hasattr(ar, '__length_hint__'))
        self.assertFalse(hasattr(ar, 'foo'))
        self.assertTrue(hasattr(ar, 'engine_id'))

    def test_getitem(self):
        ar = self.client[:].apply_async(wait, 0.5)
        assert ar['completed'] == [None] * len(ar)
        self.assertRaises(KeyError, lambda: ar['foo'])
        ar.get(5)
        self.assertRaises(KeyError, lambda: ar['foo'])
        assert isinstance(ar['completed'], list)
        assert ar.completed == ar['completed']
        assert all(isinstance(dt, datetime) for dt in ar.completed)

    def test_single_result(self):
        ar = self.client[-1].apply_async(wait, 0.5)
        self.assertRaises(KeyError, lambda: ar['foo'])
        assert ar['completed'] is None
        assert ar.get(5) == 0.5
        assert isinstance(ar['completed'], datetime)
        assert isinstance(ar.completed, datetime)
        self.assertEqual(ar.completed, ar['completed'])

    def test_abort(self):
        e = self.client[-1]
        ar = e.execute('import time; time.sleep(1)', block=False)
        ar2 = e.apply_async(lambda: 2)
        ar2.abort()
        self.assertRaises(error.TaskAborted, ar2.get)
        ar.get()

    def test_len(self):
        v = self.client.load_balanced_view()
        ar = v.map_async(lambda x: x, list(range(10)))
        self.assertEqual(len(ar), 10)
        ar = v.apply_async(lambda x: x, list(range(10)))
        self.assertEqual(len(ar), 1)
        ar = self.client[:].apply_async(lambda x: x, list(range(10)))
        self.assertEqual(len(ar), len(self.client.ids))

    def test_wall_time_single(self):
        v = self.client.load_balanced_view()
        ar = v.apply_async(time.sleep, 0.25)
        self.assertRaises(TimeoutError, getattr, ar, 'wall_time')
        ar.get(2)
        self.assertTrue(ar.wall_time < 1.0)
        self.assertTrue(ar.wall_time > 0.2)

    def test_wall_time_multi(self):
        self.minimum_engines(4)
        v = self.client[:]
        ar = v.apply_async(time.sleep, 0.25)
        self.assertRaises(TimeoutError, getattr, ar, 'wall_time')
        ar.get(2)
        self.assertTrue(ar.wall_time < 1.0)
        self.assertTrue(ar.wall_time > 0.2)

    def test_serial_time_single(self):
        v = self.client.load_balanced_view()
        ar = v.apply_async(time.sleep, 0.25)
        self.assertRaises(TimeoutError, getattr, ar, 'serial_time')
        ar.get(2)
        self.assertTrue(ar.serial_time < 1.0)
        self.assertTrue(ar.serial_time > 0.2)

    def test_serial_time_multi(self):
        self.minimum_engines(4)
        v = self.client[:]
        ar = v.apply_async(time.sleep, 0.25)
        self.assertRaises(TimeoutError, getattr, ar, 'serial_time')
        ar.get(2)
        self.assertTrue(ar.serial_time < 2.0)
        self.assertTrue(ar.serial_time > 0.8)

    def test_elapsed_single(self):
        v = self.client.load_balanced_view()
        ar = v.apply_async(time.sleep, 0.25)
        while not ar.ready():
            time.sleep(0.01)
            self.assertTrue(ar.elapsed < 1)
        self.assertTrue(ar.elapsed < 1)
        ar.get(2)

    def test_elapsed_multi(self):
        v = self.client[:]
        ar = v.apply_async(time.sleep, 0.25)
        while not ar.ready():
            time.sleep(0.01)
            self.assertLess(ar.elapsed, 1)
        self.assertLess(ar.elapsed, 1)
        ar.get(2)

    def test_hubresult_timestamps(self):
        self.minimum_engines(4)
        v = self.client[:]
        ar = v.apply_async(time.sleep, 0.25)
        ar.get(2)
        rc2 = ipp.Client(profile='iptest')
        # must have try/finally to close second Client, otherwise
        # will have dangling sockets causing problems
        try:
            time.sleep(0.25)
            hr = rc2.get_result(ar.msg_ids)
            self.assertTrue(hr.elapsed > 0.0, "got bad elapsed: %s" % hr.elapsed)
            hr.get(1)
            self.assertTrue(
                hr.wall_time < ar.wall_time + 0.2,
                f"got bad wall_time: {hr.wall_time} > {ar.wall_time}",
            )
            self.assertEqual(hr.serial_time, ar.serial_time)
        finally:
            rc2.close()

    def test_display_empty_streams_single(self):
        """empty stdout/err are not displayed (single result)"""
        self.minimum_engines(1)

        v = self.client[-1]
        ar = v.execute("print (5555)")
        ar.get(5)
        with capture_output() as io:
            ar.display_outputs()
        self.assertEqual(io.stderr, '')
        self.assertEqual('5555\n', io.stdout)

        ar = v.execute("a=5")
        ar.get(5)
        with capture_output() as io:
            ar.display_outputs()
        self.assertEqual(io.stderr, '')
        self.assertEqual(io.stdout, '')

    def test_display_empty_streams_type(self):
        """empty stdout/err are not displayed (groupby type)"""
        self.minimum_engines(1)

        v = self.client[:]
        ar = v.execute("print (5555)")
        ar.get(5)
        with capture_output() as io:
            ar.display_outputs()
        self.assertEqual(io.stderr, '')
        self.assertEqual(io.stdout.count('5555'), len(v), io.stdout)
        self.assertFalse('\n\n' in io.stdout, io.stdout)
        self.assertEqual(io.stdout.count('[stdout:'), len(v), io.stdout)

        ar = v.execute("a=5")
        ar.get(5)
        with capture_output() as io:
            ar.display_outputs()
        self.assertEqual(io.stderr, '')
        self.assertEqual(io.stdout, '')

    def test_display_empty_streams_engine(self):
        """empty stdout/err are not displayed (groupby engine)"""
        self.minimum_engines(1)

        v = self.client[:]
        ar = v.execute("print (5555)")
        ar.get(5)
        with capture_output() as io:
            ar.display_outputs('engine')
        self.assertEqual(io.stderr, '')
        self.assertEqual(io.stdout.count('5555'), len(v), io.stdout)
        self.assertFalse('\n\n' in io.stdout, io.stdout)
        self.assertEqual(io.stdout.count('[stdout:'), len(v), io.stdout)

        ar = v.execute("a=5")
        ar.get(5)
        with capture_output() as io:
            ar.display_outputs('engine')
        self.assertEqual(io.stderr, '')
        self.assertEqual(io.stdout, '')

    def test_await_data(self):
        """asking for ar.data flushes outputs"""
        self.minimum_engines(1)

        v = self.client[-1]
        ar = v.execute(
            '\n'.join(
                [
                    "import time",
                    "from ipyparallel.datapub import publish_data",
                    "for i in range(5):",
                    "    publish_data(dict(i=i))",
                    "    time.sleep(0.1)",
                ]
            ),
            block=False,
        )
        found = set()
        tic = time.time()
        # timeout after 10s
        while time.time() <= tic + 10:
            if ar.data:
                i = ar.data['i']
                found.add(i)
                if i == 4:
                    break
            time.sleep(0.05)

        ar.get(5)
        assert 4 in found
        assert len(found) > 1, (
            "should have seen data multiple times, but got: %s" % found
        )

    def test_not_single_result(self):
        save_build = self.client._build_targets

        def single_engine(*a, **kw):
            idents, targets = save_build(*a, **kw)
            return idents[:1], targets[:1]

        ids = single_engine('all')[1]
        self.client._build_targets = single_engine
        for targets in ('all', None, ids):
            dv = self.client.direct_view(targets=targets)
            ar = dv.apply_async(lambda: 5)
            self.assertEqual(ar.get(10), [5])
        self.client._build_targets = save_build

    def test_owner_pop(self):
        self.minimum_engines(1)

        view = self.client[-1]
        ar = view.apply_async(lambda: 1)
        ar.get()
        ar.wait_for_output()
        msg_id = ar.msg_ids[0]
        self.assertNotIn(msg_id, self.client.results)
        self.assertNotIn(msg_id, self.client.metadata)

    def test_dir(self):
        """dir(AsyncResult)"""
        view = self.client[-1]
        ar = view.apply_async(lambda: 1)
        ar.get()
        d = dir(ar)
        self.assertIn('stdout', d)
        self.assertIn('get', d)

    def test_wait_for_send(self):
        view = self.client[-1]
        view.track = True
        with self.assertRaises(TimeoutError):
            # this test can fail if the send happens too quickly
            # e.g. the IO thread takes control for too long,
            # so run the test a few times
            for i in range(3):
                if i > 0:
                    print("Retrying test_wait_for_send")
                data = os.urandom(10 * 1024 * 1024)
                ar = view.apply_async(lambda x: x, data)
                ar.wait_for_send(0)
        ar.wait_for_send(10)

    def test_return_exceptions(self):
        view = self.client.load_balanced_view()

        def fail_on_2(n):
            if n == 2:
                raise ValueError("two!")
            return n

        amr = view.map(fail_on_2, range(4), return_exceptions=True)
        assert amr._return_exceptions
        rlist = list(amr)
        error = rlist[2]
        assert isinstance(error, ipp.RemoteError)
        expected = [0, 1, error, 3]
        assert list(amr) == expected
        assert amr.get() == expected

    def test_return_exceptions_postmortem(self):
        self.minimum_engines(3)
        dv = self.client[:]
        bad_id = dv.targets[1]
        dv.scatter("rank", dv.targets, flatten=True)

        def fail_on_bad_id(rank, bad_id):
            if rank == bad_id:
                raise ValueError(f"{rank} is bad!")
            return rank

        ar = dv.apply_async(fail_on_bad_id, ipp.Reference('rank'), bad_id)
        with raises_remote(ValueError):
            ar.get()

        result = ar.get(return_exceptions=True)
        assert result[:1] == dv.targets[:1]
        assert result[2:] == dv.targets[2:]
        assert isinstance(result[1], ipp.RemoteError)

    def test_split(self):
        self.minimum_engines(3)
        dv = self.client[:]
        parent = dv.apply_async(os.getpid)
        children = parent.split()
        for child in children:
            assert len(child.msg_ids) == 1
        # split is identity when only one message
        assert children[0].split() == (children[0],)
        result = parent.get(timeout=10)
        # get doubly-nested lists because these are
        split_results = [ar.get(timeout=10) for ar in children]
        assert split_results == result

    def test_split_map_result(self):
        v = self.client.load_balanced_view()
        amr = v.map_async(lambda x: x, range(5))
        splits = amr.split()
        amr.get(timeout=10)
        for i, ar in zip(range(5), splits):
            assert type(ar) is ipp.AsyncResult  # not a MapResult!
            assert ar.done()
            assert ar.get() == [[i]]

    def test_wait_first_exception(self):
        dv = self.client[:]

        def fail(i):
            print(i)
            import time

            if i == 0:
                print(1 / i)
            time.sleep(1)
            return i

        dv.scatter('rank', range(len(dv)), flatten=True, block=True)
        amr = dv.apply_async(fail, ipp.Reference("rank"))
        tic = time.perf_counter()
        done, pending = amr.wait(timeout=5, return_when=ipp.FIRST_EXCEPTION)
        assert done
        assert len(done) == 1
        first_done = done.pop()
        assert first_done.msg_ids == amr.msg_ids[:1]
        assert amr.wait(timeout=10) == True
        done, pending = amr.wait(timeout=0, return_when=ipp.FIRST_EXCEPTION)
        assert pending == set()
        assert len(done) == len(amr)

    def test_map_wait_first_exception(self):
        dv = self.client[:]

        def fail(i):
            print(i)
            import time

            if i == 0:
                print(1 / i)
            time.sleep(1)
            return i

        amr = dv.map_async(fail, range(len(dv)))
        tic = time.perf_counter()
        done, pending = amr.wait(timeout=5, return_when=ipp.FIRST_EXCEPTION)
        assert done
        assert len(done) == 1
        first_done = done.pop()
        assert first_done.msg_ids == amr.msg_ids[:1]
        assert amr.wait(timeout=10) == True
        done, pending = amr.wait(timeout=0, return_when=ipp.FIRST_EXCEPTION)
        assert pending == set()
        assert len(done) == len(amr)

    def test_progress(self):
        dv = self.client[:]
        amr = dv.map_async(time.sleep, [0.2] * 2 * len(dv))
        assert len(amr) == len(dv) * 2
        assert amr.progress == 0
        amr.wait_interactive()
        assert amr.progress == len(amr)
