from dace import types
from dace.graph import nodes
from dace.codegen.instrumentation.provider import InstrumentationProvider
from dace.codegen.prettycode import CodeIOStream


class CUDAEventProvider(InstrumentationProvider):
    """ Timing instrumentation that prints wall-clock time directly after
        timed execution is complete. """

    def on_sdfg_begin(self, sdfg, local_stream, global_stream):
        global_stream.write('#include <cuda_runtime.h>')

        # For other file headers
        if len(sdfg.global_code) == 0:
            sdfg.set_global_code('#include <cuda_runtime.h>')
        else:
            sdfg.set_global_code(sdfg.global_code +
                                 '\n#include <cuda_runtime.h>')

    def _idstr(self, sdfg, state, node):
        if state is not None:
            if node is not None:
                node = state.node_id(node)
            else:
                node = ''
            state = sdfg.node_id(state)
        else:
            state = ''
        return str(state) + '_' + str(node)

    def _get_sobj(self, node):
        # Get object behind scope
        if hasattr(node, 'consume'):
            return node.consume
        else:
            return node.map

    def _create_event(self, id):
        return '''cudaEvent_t __dace_ev_{id};
cudaEventCreate(&__dace_ev_{id});'''.format(id=id)

    def _destroy_event(self, id):
        return 'cudaEventDestroy(__dace_ev_%s);' % id

    def _record_event(self, id, stream):
        return 'cudaEventRecord(__dace_ev_%s, dace::cuda::__streams[%d]);' % (
            id, stream)

    def _report(self, timer_name: str, sdfg=None, state=None, node=None):
        idstr = self._idstr(sdfg, state, node)

        return '''float __dace_ms_{id} = -1.0f;
cudaEventSynchronize(__dace_ev_e{id});
cudaEventElapsedTime(&__dace_ms_{id}, __dace_ev_b{id}, __dace_ev_e{id});
printf("(CUDA) {timer_name}: %f ms\\n", __dace_ms_{id});'''.format(
            id=idstr, timer_name=timer_name)

    # Code generation hooks
    def on_state_begin(self, sdfg, state, local_stream, global_stream):
        # Create CUDA events for each instrumented scope in the state
        for node in state.nodes():
            if isinstance(node, nodes.EntryNode):
                s = self._get_sobj()
                if s.instrument == types.InstrumentationType.CUDA_Events:
                    idstr = self._idstr(sdfg, state, node)
                    local_stream.write(
                        self._create_event('b' + idstr), sdfg, state, node)
                    local_stream.write(
                        self._create_event('e' + idstr), sdfg, state, node)

        # Create and record a CUDA event for the entire state
        if state.instrument == types.InstrumentationType.CUDA_Events:
            idstr = 'b' + self._idstr(sdfg, state)
            local_stream.write(self._create_event(idstr), sdfg, state)
            local_stream.write(self._record_event(idstr, 0), sdfg, state)

    def on_state_end(self, sdfg, state, local_stream, global_stream):
        # Record and measure state stream event
        if state.instrument == types.InstrumentationType.CUDA_Events:
            idstr = self._idstr(sdfg, state)
            local_stream.write(self._record_event('e' + idstr, 0), sdfg, state)
            local_stream.write(
                self._report('State %s' % state.label, sdfg, state), sdfg,
                state)
            local_stream.write(self._destroy_event('b' + idstr), sdfg, state)
            local_stream.write(self._destroy_event('e' + idstr), sdfg, state)

        # Destroy CUDA events for scopes in the state
        for node in state.nodes():
            if isinstance(node, nodes.EntryNode):
                s = self._get_sobj()
                if s.instrument == types.InstrumentationType.CUDA_Events:
                    idstr = self._idstr(sdfg, state, node)
                    local_stream.write(
                        self._destroy_event('b' + idstr), sdfg, state, node)
                    local_stream.write(
                        self._destroy_event('e' + idstr), sdfg, state, node)

    def on_scope_entry(self, sdfg, state, node, outer_stream, inner_stream,
                       global_stream):
        s = self._get_sobj(node)
        if s.instrument == types.InstrumentationType.CUDA_Events:
            idstr = 'b' + self._idstr(sdfg, state, node)
            outer_stream.write(
                self._record_event(idstr, node._cuda_stream), sdfg, state,
                node)

    def on_scope_exit(self, sdfg, state, node, outer_stream, inner_stream,
                      global_stream):
        entry_node = state.entry_node(node)
        s = self._get_sobj(node)
        if s.instrument == types.InstrumentationType.CUDA_Events:
            idstr = 'e' + self._idstr(sdfg, state, node)
            outer_stream.write(
                self._record_event(idstr, node._cuda_stream), sdfg, state,
                node)
            outer_stream.write(
                self._report('%s %s' % (type(s).__name__, s.label), sdfg,
                             state, entry_node), sdfg, state, node)
