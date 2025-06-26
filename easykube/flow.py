import functools
import inspect


class SyncExecutor:
    """
    Flow executor for synchronous contexts.
    """

    def execute_flow(self, flow):
        """
        Executes a flow and returns the result.
        """
        try:
            action = flow.send
            to_send = None
            while True:
                try:
                    yielded_obj = action(to_send)
                except StopIteration as exc:
                    # If the generator returns, we are done
                    return exc.value
                try:
                    if inspect.isgenerator(yielded_obj):
                        to_send = self.execute_flow(yielded_obj)
                    else:
                        to_send = yielded_obj
                except Exception as exc:
                    action = flow.throw
                    to_send = exc
                else:
                    action = flow.send
        finally:
            flow.close()


class AsyncExecutor:
    """
    Flow executor for asynchronous contexts.
    """

    async def execute_flow(self, flow):
        """
        Executes a flow and returns an awaitable containing the result.
        """
        try:
            action = flow.send
            to_send = None
            while True:
                try:
                    yielded_obj = action(to_send)
                except StopIteration as exc:
                    # If the generator returns, we are done
                    return exc.value
                try:
                    if inspect.isgenerator(yielded_obj):
                        to_send = await self.execute_flow(yielded_obj)
                    elif inspect.isawaitable(yielded_obj):
                        to_send = await yielded_obj
                    else:
                        to_send = yielded_obj
                except Exception as exc:
                    action = flow.throw
                    to_send = exc
                else:
                    action = flow.send
        finally:
            flow.close()


class Flowable:
    """
    Base classes for objects that can support flows.
    """

    __flow_executor__ = None

    @property
    def is_async(self):
        return isinstance(self.__flow_executor__, AsyncExecutor)

    def get_flow_executor(self):
        return self.__flow_executor__


def flow(method):
    """
    Decorator that marks a method of a flowable as a flow that can be resolved
    synchronously or asynchronously depending on the executor that is in use.
    """

    @functools.wraps(method)
    def wrapper(flowable, *args, **kwargs):
        gen = method(flowable, *args, **kwargs)
        if inspect.isgenerator(gen):
            return flowable.get_flow_executor().execute_flow(gen)
        else:
            return gen

    return wrapper
