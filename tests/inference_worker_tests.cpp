#include "docksr/core/inference_worker.hpp"

#include <array>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace inf = docksr::inference;
namespace {
unsigned checks{}, failures{}, groups{};
std::vector<std::string> observations;
void check(bool value, const char* message) {
  ++checks;
  if (!value) { ++failures; std::cerr << "FAIL: " << message << '\n'; }
}
template<class F> void throws(F&& fn, const char* message) {
  bool caught = false;
  try { fn(); } catch (const std::exception&) { caught = true; }
  check(caught, message);
}
inf::Request request(std::uint64_t frame = 1, std::uint64_t generation = 1,
                     std::uint64_t submitted = 10, std::uint64_t deadline = 100) {
  inf::Request r;
  r.session_id = "contract-session"; r.frame_id = frame; r.configuration_generation = generation;
  r.model_id = "owned-contract"; r.model_sha256 = std::string(64, 'a');
  r.source_extent = {2, 2}; r.source_format = "RGB8";
  r.tensor_shape = {1, 2, 2, 3}; r.tensor_dtype = "int8"; r.tensor_layout = "NHWC";
  r.buffer_size = 12; r.buffer_stride = {12, 6, 3, 1};
  r.submit_timestamp = submitted; r.deadline = deadline; r.trace_id = "trace-" + std::to_string(frame);
  r.expected_output_extent = {4, 4}; r.expected_output_format = "RGB_INT8";
  r.expected_output_shape = {1, 4, 4, 3}; r.expected_output_dtype = "int8";
  r.expected_output_layout = "NHWC";
  return r;
}
std::vector<std::uint8_t> input(const inf::Request& r) { return std::vector<std::uint8_t>(r.buffer_size, 7); }
inf::Result mock(const inf::Request& r) { inf::DeterministicMockBackend backend; return backend.execute(r, input(r)); }
inf::WorkItem start(inf::Worker& worker, const inf::Request& r) {
  const auto submitted = worker.submit(r, input(r), r.submit_timestamp);
  check(submitted.accepted && submitted.ticket.has_value(), "valid request admitted");
  const auto job = worker.start_next(r.submit_timestamp);
  check(job.has_value(), "valid request started");
  return job.value();
}

void signatures() {
  ++groups;
  check(inf::validate_request(request(), 64u * 1024u * 1024u).empty(), "valid RGB signature");
  check(inf::tensor_bytes(std::array<std::uint64_t, 4>{1, 3, 256, 256}, "float32") == 786432,
        "independent FLOAT32 input payload");
  check(inf::tensor_bytes(std::array<std::uint64_t, 4>{1, 3, 768, 768}, "float32") == 7077888,
        "independent FLOAT32 output payload");
  check(inf::contiguous_strides(std::array<std::uint64_t, 4>{1, 3, 2, 4}, "float32") ==
        std::vector<std::uint64_t>({96, 32, 16, 4}), "NCHW byte strides");
  check(!inf::tensor_bytes(std::array<std::uint64_t, 2>{1, 0}, "int8"), "zero tensor dimension refused");
  check(!inf::tensor_bytes(std::array<std::uint64_t, 1>{8193}, "int8"), "dimension bound");
  check(!inf::tensor_bytes(std::array<std::uint64_t, 8>{8192,8192,8192,8192,8192,8192,8192,8192}, "float32"), "tensor multiplication overflow");
  check(!inf::tensor_bytes(std::array<std::uint64_t, 1>{3}, "object"), "unsupported dtype");
  const std::vector<std::function<void(inf::Request&)>> corrupt = {
    [](auto& r){r.schema_version="2.0.0";}, [](auto& r){r.session_id="bad session";},
    [](auto& r){r.trace_id=std::string(129,'x');}, [](auto& r){r.frame_id=0;},
    [](auto& r){r.configuration_generation=0;}, [](auto& r){r.model_sha256="bad";},
    [](auto& r){r.model_sha256=std::string(64,'A');}, [](auto& r){r.source_extent={0,2};},
    [](auto& r){r.source_format="YCbCr";}, [](auto& r){r.buffer_size=13;},
    [](auto& r){r.buffer_ownership="BORROWED";}, [](auto& r){r.buffer_stride={12,1,3,6};},
    [](auto& r){r.tensor_layout="HWCN";}, [](auto& r){r.tensor_shape={1,2,2,4};},
    [](auto& r){r.expected_output_format="RGB_FLOAT32";}, [](auto& r){r.expected_output_extent={3,4};},
    [](auto& r){r.source_extent={3,2};}, [](auto& r){r.deadline=r.submit_timestamp;}
  };
  for (const auto& change : corrupt) { auto r=request(); change(r); check(!inf::validate_request(r, 64u*1024u*1024u).empty(), "invalid request rejected"); }
  auto tiled=request(); tiled.source_extent={8,8};
  tiled.tile=inf::TilePlacement{6,6,2,2,0,0,0,0,12,12,4,4};
  check(inf::validate_request(tiled, 1024).empty(), "partial source core with explicit global placement");
  observations.push_back(inf::request_json(tiled));
  tiled.tile->source_x=7;
  check(inf::validate_request(tiled,1024)=="TILE_PLACEMENT", "tile source bounds");
  tiled.tile->source_x=6; tiled.tile->halo_left=1;
  check(inf::validate_request(tiled,1024)=="TILE_PLACEMENT", "tile halo bounds");
}

void admission_limits() {
  ++groups;
  throws([]{inf::Worker w("session",0);}, "zero generation refused");
  throws([]{inf::Worker w("bad session");}, "invalid session refused");
  throws([]{inf::Worker w("session",1,{0,12,48,64});}, "zero slots refused");
  throws([]{inf::Worker w("session",1,{65,12,48,64});}, "maximum slots enforced");
  throws([]{inf::Worker w("session",1,{1,0,48,64});}, "zero queue budget refused");
  inf::Worker queue("contract-session",1,{2,12,96,64});
  check(queue.submit(request(),input(request()),10).accepted,"exact input budget admitted");
  check(!queue.submit(request(2),input(request(2)),10).accepted && queue.last_error()=="QUEUE_BYTE_LIMIT", "input budget enforced across jobs");
  inf::Worker result("contract-session",1,{2,24,47,64});
  check(!result.submit(request(),input(request()),10).accepted && result.last_error()=="RESULT_BYTE_LIMIT", "output reservation enforced before execution");
  inf::Worker capacity("contract-session",1,{2,12,96,64});
  auto roomy=input(request()); roomy.reserve(24);
  check(!capacity.submit(request(),std::move(roomy),10).accepted,"owned vector capacity counts toward queue budget");
  inf::Worker slots("contract-session",1,{1,24,96,64});
  check(slots.submit(request(),input(request()),10).accepted,"one slot admitted");
  check(!slots.submit(request(2),input(request(2)),10).accepted && slots.last_error()=="IN_FLIGHT_LIMIT", "in-flight limit");
  inf::Worker invalid("contract-session");
  auto wrong=request();wrong.session_id="other";
  check(!invalid.submit(wrong,input(wrong),10).accepted,"session mismatch refused at admission");
  wrong=request(1,2);check(!invalid.submit(wrong,input(wrong),10).accepted,"generation mismatch refused at admission");
  wrong=request(1,1,20,100);check(!invalid.submit(wrong,input(wrong),10).accepted,"future submit timestamp refused");
  check(!invalid.submit(request(),std::vector<std::uint8_t>(11),10).accepted,"input byte mismatch refused");
}

void lifecycle() {
  ++groups;inf::Worker worker("contract-session");const auto r=request();
  const auto job=start(worker,r);observations.push_back(inf::request_json(*job.request));
  check(job.input.size()==12 && job.input.front()==7,"started view references owned input");
  check(!worker.consume(job.ticket,r.session_id,r.frame_id,r.configuration_generation,10),"submission is not completion");
  check(!worker.release(job.ticket,10),"producer cannot release before completion");
  check(worker.complete(job.ticket,mock(r),11),"valid completion accepted");
  check(worker.counts().completed==1 && worker.counts().consumed==0,"completion is not consumption");
  check(worker.queue_bytes()==12 && worker.result_bytes()==48 && worker.reserved_result_bytes()==48,"input and output remain bounded and owned");
  check(worker.allocation_high_water_bytes()==60,"actual owned vector highwater independent of reservation");
  check(!worker.consume(job.ticket,r.session_id,2,1,12),"frame N cannot satisfy N+1");
  check(!worker.consume(job.ticket,"wrong",1,1,12),"wrong consumer session rejected");
  check(!worker.consume(job.ticket,r.session_id,1,2,12),"wrong consumer generation rejected");
  const auto* consumed=worker.consume(job.ticket,r.session_id,1,1,12);
  check(consumed && consumed->valid && consumed->output.size()==48,"exact output consumed");
  check(consumed && consumed->ledger.submit_to_complete_duration==1 && consumed->ledger.complete_to_consume_duration==1,"host supplied monotonic intervals distinct");
  if(consumed)observations.push_back(inf::result_json(*consumed));
  check(!worker.consume(job.ticket,r.session_id,1,1,12),"duplicate consumption rejected");
  check(!worker.complete(job.ticket,mock(r),12),"duplicate completion rejected");
  check(worker.release(job.ticket,13),"consumer release acknowledged");
  check(worker.in_flight()==0 && worker.queue_bytes()==0 && worker.result_bytes()==0 && worker.reserved_result_bytes()==0,"release clears all storage and reservation");
  check(!worker.release(job.ticket,13),"duplicate release rejected");
  check(!worker.submit(r,input(r),13).accepted,"old frame ID cannot re-enter generation");
  check(!worker.advance(12),"monotonic clock reversal rejected");
}

void deadlines() {
  ++groups;
  inf::Worker queued("contract-session",1,{1,64,64,64});
  check(queued.submit(request(),input(request()),10).accepted,"queued expiry admission");
  check(queued.advance(100) && queued.in_flight()==0,"unstarted deadline cancellation releases storage");
  check(!queued.start_next(100),"expired queued job never starts");
  inf::Worker running("contract-session",1,{1,64,64,64});const auto r=request();auto job=start(running,r);
  check(running.advance(100) && running.in_flight()==1 && running.queue_bytes()==12,"deadline never frees running producer input");
  auto later=request(2,1,100,200);check(!running.submit(later,input(later),100).accepted,"timed-out active producer still occupies slot");
  check(!running.complete(job.ticket,mock(r),101),"late completion discarded even when result timestamp was earlier");
  check(running.in_flight()==0 && running.queue_bytes()==0,"stopped late producer storage retired");
  inf::Worker ready("contract-session");job=start(ready,r);check(ready.complete(job.ticket,mock(r),11),"ready before expiry");
  check(ready.advance(100) && ready.in_flight()==0,"unconsumed output can be safely discarded at expiry");
  inf::Worker consumer("contract-session");job=start(consumer,r);check(consumer.complete(job.ticket,mock(r),11),"consumer case completion");
  const auto* held=consumer.consume(job.ticket,r.session_id,1,1,12);
  check(held!=nullptr,"consumer acquired before deadline");
  check(consumer.advance(100) && consumer.in_flight()==1 && consumer.result_bytes()==48,"deadline never frees consumer-owned output");
  check(held && held->output.size()==48 && !held->valid,"held result storage survives fallback invalidation");
  if(held)observations.push_back(inf::result_json(*held));
  check(consumer.release(job.ticket,101) && consumer.in_flight()==0,"consumer explicitly releases expired output");
}

void result_guards() {
  ++groups;
  const std::vector<std::function<void(inf::Result&)>> corrupt={
    [](auto& r){r.frame_id++;}, [](auto& r){r.session_id="other";}, [](auto& r){r.configuration_generation++;},
    [](auto& r){r.model_id="other";}, [](auto& r){r.model_sha256=std::string(64,'b');}, [](auto& r){r.trace_id="other";},
    [](auto& r){r.schema_version="2";}, [](auto& r){r.evidence_class="REAL_NPU";},
    [](auto& r){r.backend_kind="CPU_REFERENCE";}, [](auto& r){r.completion_timestamp=9;},
    [](auto& r){r.completion_timestamp=12;}, [](auto& r){r.output_extent={3,4};},
    [](auto& r){r.output_dtype="float32";}, [](auto& r){r.output_format="RGB8";},
    [](auto& r){r.output_layout="NCHW";}, [](auto& r){r.output_shape={1,4,3,4};},
    [](auto& r){r.output.pop_back();}, [](auto& r){r.output.reserve(96);},
    [](auto& r){r.fallback_reason="HAS_ERROR";}, [](auto& r){r.copy_count=1;},
    [](auto& r){r.logical_bytes++;}, [](auto& r){r.inference_duration.reset();},
    [](auto& r){r.inference_duration=2;}, [](auto& r){r.ledger.gpu_upload_bytes=0;},
    [](auto& r){r.ledger.timing_class="OBSERVED_HOST_CPU";}, [](auto& r){r.ledger.host_copy_bytes=1;},
    [](auto& r){r.ledger.inference_input_logical_bytes=0;}, [](auto& r){r.ledger.runtime_internal_copy_status="ZERO_COPY";}
  };
  for(const auto& change:corrupt){inf::Worker worker("contract-session");const auto r=request();const auto job=start(worker,r);auto bad=mock(r);change(bad);
    check(!worker.complete(job.ticket,std::move(bad),11),"corrupt result rejected");
    check(worker.in_flight()==0 && worker.result_bytes()==0,"malformed stopped producer retired without publication");}
  inf::Worker worker("contract-session");const auto r=request();const auto job=start(worker,r);auto forged=job.ticket;++forged.serial;
  check(!worker.complete(forged,mock(r),11) && worker.in_flight()==1,"wrong trusted ticket cannot retire active producer");
  check(worker.complete(job.ticket,mock(r),11),"real producer remains usable after stale event");
  check(worker.release(job.ticket,12),"ready output may be deliberately discarded");
}

void invalidation_and_ordering() {
  ++groups;inf::Worker worker("contract-session");const auto first=request();const auto job=start(worker,first);
  check(worker.submit(request(2),input(request(2)),10).accepted,"second queued frame");
  check(worker.invalidate(9,12),"external generation can increase independently of internal ticket sequence");
  check(worker.in_flight()==1 && worker.queue_bytes()==12,"invalidation cancels queued but retains running producer");
  check(!worker.complete(job.ticket,mock(first),13) && worker.in_flight()==0,"old-generation output discarded");
  auto current=request(3,9,13,100);auto next=start(worker,current);
  check(worker.complete(next.ticket,mock(current),14),"new configuration can execute");
  check(worker.consume(next.ticket,current.session_id,3,9,15)!=nullptr,"new-generation output consumed");
  check(worker.release(next.ticket,16),"new configuration release");
  check(!worker.invalidate(9,16),"duplicate generation rejected");
  inf::Worker out_of_order("contract-session");auto a=start(out_of_order,request());auto b=start(out_of_order,request(2));
  check(out_of_order.complete(b.ticket,mock(request(2)),11),"later frame completes first");
  check(out_of_order.consume(b.ticket,"contract-session",2,1,12)!=nullptr,"later frame consumed");
  check(!out_of_order.complete(a.ticket,mock(request()),13),"older completion cannot follow consumed newer frame");
  check(out_of_order.release(b.ticket,14),"later frame released");
}

void shutdown_and_backends() {
  ++groups;const auto r=request();
  inf::UnavailableBackend unavailable;auto absent=unavailable.execute(r,input(r));
  check(!absent.valid && absent.evidence_class=="NOT_RUN" && absent.fallback_reason=="BACKEND_UNAVAILABLE","unavailable backend truthful bounded failure");
  observations.push_back(inf::result_json(absent));
  inf::CpuReferenceBackend missing({});auto error=missing.execute(r,input(r));
  check(!error.valid && error.evidence_class=="NOT_RUN" && error.fallback_reason=="CPU_EXECUTOR_UNAVAILABLE","missing executor is not CPU inference");
  observations.push_back(inf::result_json(error));
  inf::CpuReferenceBackend throwing([](const auto&,auto)->inf::Result{throw std::runtime_error("fail");});
  check(throwing.execute(r,input(r)).evidence_class=="NOT_RUN","executor exception cannot claim observed inference");
  inf::CpuReferenceBackend honest_failure([](const auto& q,auto){return inf::failure(q,"CPU_REFERENCE","NOT_RUN","CPU_PROCESS_TIMEOUT",q.submit_timestamp);});
  check(honest_failure.execute(r,input(r)).fallback_reason=="CPU_PROCESS_TIMEOUT","truthful unrun child failure preserved");
  inf::CpuReferenceBackend lying([](const auto& q,auto){return mock(q);});
  check(lying.execute(r,input(r)).fallback_reason=="CPU_RECEIPT_MISMATCH","CPU wrapper never relabels simulated receipt");
  inf::Worker failed("contract-session");auto stopped=start(failed,r);
  check(!failed.complete(stopped.ticket,honest_failure.execute(r,input(r)),11) && failed.in_flight()==0,"invalid completed child retired without output");
  inf::Worker worker("contract-session");auto active=start(worker,r);
  check(!worker.acknowledge_quiescence(10),"quiescence requires explicit shutdown");
  check(worker.shutdown(11) && worker.in_flight()==1 && worker.queue_bytes()==12,"shutdown retains active producer");
  check(!worker.shutdown_complete() && !worker.start_next(11),"shutdown stops new execution but awaits producer");
  auto next=request(2,1,11,100);check(!worker.submit(next,input(next),11).accepted,"shutdown rejects admission");
  check(!worker.complete(active.ticket,mock(r),12) && worker.shutdown_complete(),"actual stopped producer completes safe shutdown");
  inf::Worker trusted("contract-session");active=start(trusted,r);check(trusted.shutdown(11),"trusted shutdown entered");
  check(trusted.acknowledge_quiescence(12) && trusted.shutdown_complete(),"trusted all-accesses-stopped acknowledgement clears storage");
  inf::Worker consumer("contract-session");active=start(consumer,r);
  check(consumer.complete(active.ticket,mock(r),11),"shutdown consumer case completes");
  const auto* held=consumer.consume(active.ticket,r.session_id,r.frame_id,r.configuration_generation,12);
  check(held && consumer.shutdown(13) && consumer.result_bytes()==48 && !consumer.shutdown_complete(),"shutdown retains acquired consumer output");
  check(held && held->output.size()==48 && !held->valid,"shutdown invalidates without freeing consumer result");
  check(consumer.release(active.ticket,14) && consumer.shutdown_complete(),"consumer acknowledgement completes shutdown");
  observations.push_back(inf::future_backends_json());
}

void nonfinite_tensors() {
  ++groups;auto r=request();r.source_format="RGB_FLOAT32";r.tensor_dtype="float32";r.buffer_size=48;
  r.buffer_stride=inf::contiguous_strides(r.tensor_shape,r.tensor_dtype);r.expected_output_dtype="float32";r.expected_output_format="RGB_FLOAT32";
  auto bytes=input(r);const float nan=std::numeric_limits<float>::quiet_NaN();std::memcpy(bytes.data(),&nan,sizeof(nan));
  inf::Worker bad("contract-session");check(!bad.submit(r,std::move(bytes),10).accepted && bad.last_error()=="NONFINITE_INPUT","NaN float tensor refused at admission");
  inf::Worker worker("contract-session");auto job=start(worker,r);auto result=mock(r);
  observations.push_back(inf::request_json(r));
  observations.push_back(inf::result_json(result));
  check(worker.complete(job.ticket,result,11),"mock FLOAT32 values are finite");check(worker.release(job.ticket,12),"float mock release");
  inf::Worker output("contract-session");job=start(output,r);result=mock(r);const float infinity=std::numeric_limits<float>::infinity();
  std::memcpy(result.output.data(),&infinity,sizeof(infinity));
  check(!output.complete(job.ticket,std::move(result),11) && output.last_error()=="NONFINITE_OUTPUT","nonfinite output cannot be consumed");
}
}

int main(int argc,char** argv) {
  const bool json=argc==2 && std::string(argv[1])=="--emit-json";
  if(argc>1 && !json)return 2;
  try{signatures();admission_limits();lifecycle();deadlines();result_guards();invalidation_and_ordering();shutdown_and_backends();nonfinite_tensors();}
  catch(const std::exception& e){++failures;std::cerr<<"Unexpected exception: "<<e.what()<<'\n';}
  if(failures){std::cerr<<failures<<" failures in "<<checks<<" checks\n";return 1;}
  if(json)for(const auto& document:observations)std::cout<<document<<'\n';
  else std::cout<<"PASS: "<<groups<<" groups, "<<checks<<" native worker checks; simulated callbacks only, no presentation/NPU proof\n";
  return 0;
}
