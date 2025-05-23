import asyncio
import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from tests.components.test_stdio_components import MockStdinReader, MockStdoutWriter

class MockSSEClient:
    def __init__(self):
        self.events = []
        self.connected = True

    async def send(self, event):
        if not self.connected:
            raise ConnectionError("Client disconnected")
        self.events.append(event)

    def disconnect(self):
        self.connected = False

@pytest.fixture
async def mock_communication_setup():
    """Set up mock stdio and SSE components for integration testing."""
    # Set up stdio mocks
    stdio_reader = MockStdinReader("")
    stdio_writer = MockStdoutWriter()

    # Set up SSE mock
    sse_client = MockSSEClient()

    return stdio_reader, stdio_writer, sse_client

@pytest.mark.asyncio
async def test_sse_stdio_interaction(mock_communication_setup):
    """Test interaction between SSE and STDIO communication channels."""
    stdio_reader, stdio_writer, sse_client = await mock_communication_setup

    # Step 1: Tool registration via STDIO
    registration_message = {
        "type": "register",
        "tool_id": "test_tool",
        "capabilities": ["capability1", "capability2"]
    }

    # Override reader's input with registration message
    stdio_reader.input_stream.write(json.dumps(registration_message) + "\n")
    stdio_reader.input_stream.seek(0)

    # Process registration
    line = await stdio_reader.readline()
    message = json.loads(line)

    # Send registration acknowledgment via stdio
    response = {
        "type": "registration_success",
        "tool_id": message["tool_id"]
    }
    await stdio_writer.write(json.dumps(response) + "\n")

    # Send SSE notification about new tool
    sse_notification = {
        "type": "tool_registered",
        "tool_id": message["tool_id"],
        "capabilities": message["capabilities"]
    }
    await sse_client.send(json.dumps(sse_notification))

    # Verify stdio response
    assert "registration_success" in stdio_writer.get_output()

    # Verify SSE notification
    assert len(sse_client.events) == 1
    assert "tool_registered" in sse_client.events[0]
    assert message["tool_id"] in sse_client.events[0]

    # Step 2: SSE event triggering STDIO message
    # Reset the writer to clear previous output
    stdio_writer = MockStdoutWriter()

    # Simulate an SSE event that should trigger a STDIO message
    sse_event = {
        "type": "request",
        "id": "sse_to_stdio_test",
        "method": "test_method",
        "params": {"param1": "value1"}
    }

    # In a real system, this would be processed by an event handler
    # that would then write to STDIO. Here we simulate that directly.
    await sse_client.send(json.dumps(sse_event))

    # Simulate the STDIO response that would be generated
    stdio_response = {
        "type": "response",
        "id": sse_event["id"],
        "result": {"status": "success"}
    }
    await stdio_writer.write(json.dumps(stdio_response) + "\n")

    # Verify the STDIO response
    assert "response" in stdio_writer.get_output()
    assert sse_event["id"] in stdio_writer.get_output()

    # Step 3: Bidirectional communication with state tracking
    # Create a simple state tracker
    state = {"last_message_id": None, "message_count": 0}

    # Send a sequence of messages in both directions
    for i in range(3):
        # STDIO to SSE
        stdio_message = {
            "type": "notification",
            "id": f"msg_{i}",
            "data": f"data_{i}"
        }

        # In a real system, this would come from STDIO input
        # Here we simulate by updating state directly
        state["last_message_id"] = stdio_message["id"]
        state["message_count"] += 1

        # Send to SSE
        await sse_client.send(json.dumps(stdio_message))

        # SSE to STDIO
        sse_response = {
            "type": "event",
            "id": f"response_{i}",
            "in_response_to": stdio_message["id"],
            "data": f"response_data_{i}"
        }

        # Process SSE response and update STDIO
        await stdio_writer.write(json.dumps(sse_response) + "\n")

    # Verify the communication flow
    assert state["message_count"] == 3
    assert state["last_message_id"] == "msg_2"
    assert len(sse_client.events) == 5  # 1 from registration + 1 from SSE event + 3 from the loop

    # Verify STDIO output contains all responses
    stdio_output = stdio_writer.get_output()
    for i in range(3):
        assert f"response_{i}" in stdio_output
        assert f"response_data_{i}" in stdio_output

@pytest.mark.asyncio
async def test_bidirectional_communication(mock_communication_setup):
    """Test bidirectional communication between stdio and SSE."""
    stdio_reader, stdio_writer, sse_client = await mock_communication_setup

    # Set up test message flow
    stdio_messages = [
        {"type": "request", "id": "1", "method": "test", "data": "stdio_data"},
        {"type": "request", "id": "2", "method": "test", "data": "more_data"}
    ]

    # Write messages to stdio
    for msg in stdio_messages:
        stdio_reader.input_stream.write(json.dumps(msg) + "\n")
    stdio_reader.input_stream.seek(0)

    # Process messages and generate SSE events
    while True:
        line = await stdio_reader.readline()
        if not line:
            break

        # Process stdio message
        message = json.loads(line)

        # Generate SSE event
        sse_event = {
            "type": "event",
            "source": "stdio",
            "data": message["data"]
        }
        await sse_client.send(json.dumps(sse_event))

        # Send response via stdio
        response = {
            "type": "response",
            "id": message["id"],
            "status": "success"
        }
        await stdio_writer.write(json.dumps(response) + "\n")

    # Verify all messages were processed
    assert len(sse_client.events) == len(stdio_messages)
    assert all("stdio" in event for event in sse_client.events)

    # Verify stdio responses
    output = stdio_writer.get_output()
    responses = [json.loads(line) for line in output.strip().split("\n")]
    assert len(responses) == len(stdio_messages)
    assert all(resp["type"] == "response" for resp in responses)

@pytest.mark.asyncio
async def test_error_propagation(mock_communication_setup):
    """Test error propagation between stdio and SSE."""
    stdio_reader, stdio_writer, sse_client = await mock_communication_setup

    # Simulate error in stdio
    error_message = {
        "type": "request",
        "id": "error_test",
        "method": "test",
        "data": "error_data"
    }
    stdio_reader.input_stream.write(json.dumps(error_message) + "\n")
    stdio_reader.input_stream.seek(0)

    # Process message and simulate error
    line = await stdio_reader.readline()
    message = json.loads(line)

    # Generate error response in stdio
    error_response = {
        "type": "error",
        "id": message["id"],
        "error": "Test error occurred"
    }
    await stdio_writer.write(json.dumps(error_response) + "\n")

    # Propagate error to SSE
    sse_error_event = {
        "type": "error_event",
        "source": "stdio",
        "error": "Test error occurred",
        "request_id": message["id"]
    }
    await sse_client.send(json.dumps(sse_error_event))

    # Verify error handling
    assert "error" in stdio_writer.get_output()
    assert len(sse_client.events) == 1
    assert "error_event" in sse_client.events[0]

@pytest.mark.asyncio
async def test_connection_state_handling(mock_communication_setup):
    """Test handling of connection state changes."""
    stdio_reader, stdio_writer, sse_client = await mock_communication_setup

    # Test normal operation
    test_message = {
        "type": "request",
        "id": "state_test",
        "method": "test"
    }
    stdio_reader.input_stream.write(json.dumps(test_message) + "\n")
    stdio_reader.input_stream.seek(0)

    # Process message while connected
    line = await stdio_reader.readline()
    message = json.loads(line)
    await sse_client.send(json.dumps({"type": "event", "data": "test"}))

    # Simulate SSE client disconnect
    sse_client.disconnect()

    # Attempt to send message after disconnect
    with pytest.raises(ConnectionError):
        await sse_client.send(json.dumps({"type": "event", "data": "test"}))

    # Send disconnect notification via stdio
    disconnect_notification = {
        "type": "notification",
        "event": "client_disconnected"
    }
    await stdio_writer.write(json.dumps(disconnect_notification) + "\n")

    # Verify disconnect handling
    assert "client_disconnected" in stdio_writer.get_output()
    assert not sse_client.connected

@pytest.mark.asyncio
async def test_race_condition_handling(mock_communication_setup):
    """Test handling of potential race conditions in message processing."""
    stdio_reader, stdio_writer, sse_client = await mock_communication_setup
    messages = [
        {"type": "request", "id": f"race_test_{i}", "sequence": i, "data": f"data_{i}"}
        for i in range(5)
    ]
    import random
    shuffled_messages = messages.copy()
    random.shuffle(shuffled_messages)
    for msg in shuffled_messages:
        stdio_reader.input_stream.write(json.dumps(msg) + "\n")
    stdio_reader.input_stream.seek(0)
    received_messages = {}
    while True:
        line = await stdio_reader.readline()
        if not line:
            break
        message = json.loads(line)
        received_messages[message["sequence"]] = message
        await sse_client.send(json.dumps({
            "type": "event",
            "sequence": message["sequence"],
            "data": message["data"]
        }))
        await stdio_writer.write(json.dumps({
            "type": "response",
            "id": message["id"],
            "sequence": message["sequence"]
        }) + "\n")
    ordered_sequences = sorted(received_messages.keys())
    assert ordered_sequences == list(range(5))
    for i, event_json in enumerate(sse_client.events):
        event = json.loads(event_json)
        assert event["sequence"] < len(messages)

@pytest.mark.asyncio
async def test_resource_cleanup(mock_communication_setup):
    """Test proper cleanup of resources after communication ends."""
    stdio_reader, stdio_writer, sse_client = await mock_communication_setup
    allocated_resources = set()
    async def allocate_resource(resource_id):
        allocated_resources.add(resource_id)
    async def release_resource(resource_id):
        allocated_resources.remove(resource_id)
    message = {"type": "request", "id": "resource_test", "resource": "test_resource"}
    stdio_reader.input_stream.write(json.dumps(message) + "\n")
    stdio_reader.input_stream.seek(0)
    line = await stdio_reader.readline()
    message = json.loads(line)
    resource_id = message["resource"]
    await allocate_resource(resource_id)
    try:
        await asyncio.sleep(0.1)
        await stdio_writer.write(json.dumps({
            "type": "response",
            "id": message["id"],
            "status": "success"
        }) + "\n")
    finally:
        await release_resource(resource_id)
    assert len(allocated_resources) == 0

@pytest.mark.asyncio
async def test_partial_message_handling(mock_communication_setup):
    """Test handling of partial or truncated messages."""
    stdio_reader, stdio_writer, sse_client = await mock_communication_setup
    partial_json = '{"type": "request", "id": "partial_test", "method": "test"'
    stdio_reader.input_stream.write(partial_json + "\n")
    stdio_reader.input_stream.seek(0)
    line = await stdio_reader.readline()
    try:
        json.loads(line)
        parsed = True
    except json.JSONDecodeError:
        parsed = False
        error_response = {
            "type": "error",
            "error": "Invalid JSON format",
            "code": "PARSE_ERROR"
        }
        await stdio_writer.write(json.dumps(error_response) + "\n")
    assert not parsed, "Parsing should have failed with partial JSON"
    assert "Invalid JSON format" in stdio_writer.get_output()
    assert "PARSE_ERROR" in stdio_writer.get_output()