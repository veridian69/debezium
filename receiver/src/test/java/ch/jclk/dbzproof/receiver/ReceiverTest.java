package ch.jclk.dbzproof.receiver;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ReceiverTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    @TempDir Path temp;
    private Receiver receiver;

    @AfterEach
    void stop() {
        if (receiver != null) receiver.close();
    }

    @Test
    void validEnvelopeRoundTrips() throws Exception {
        Paths paths = start();
        String envelope = "{\"before\":null,\"after\":{\"id\":9,\"total_cents\":1250},\"source\":{\"schema\":\"timecritical\",\"table\":\"orders\"},\"op\":\"c\"}";
        assertEquals(200, post(envelope).statusCode());

        assertEquals(JSON.readTree(envelope), JSON.readTree(Files.readString(paths.events)));
        JsonNode receipt = receipt(paths, 0);
        assertEquals("event", receipt.path("kind").asText());
        assertEquals(200, receipt.path("status").asInt());
        assertEquals("c", receipt.path("summary").path("op").asText());
        assertEquals("timecritical", receipt.path("summary").path("schema").asText());
        assertEquals("orders", receipt.path("summary").path("table").asText());
        assertEquals(9, receipt.path("summary").path("key").path("id").asInt());
    }

    @Test
    void tombstonesDoNotCreateEvents() throws Exception {
        Paths paths = start();
        assertEquals(204, post("").statusCode());
        assertEquals(204, post("null").statusCode());
        assertFalse(Files.exists(paths.events));
        assertEquals("tombstone", receipt(paths, 0).path("kind").asText());
        assertEquals("tombstone", receipt(paths, 1).path("kind").asText());
    }

    @Test
    void invalidJsonIsRejectedAndRecorded() throws Exception {
        Paths paths = start();
        assertEquals(400, post("{not-json").statusCode());
        assertFalse(Files.exists(paths.events));
        assertEquals("invalid", receipt(paths, 0).path("kind").asText());
    }

    @Test
    void eventWriteFailureReturnsServerError() throws Exception {
        Path parentFile = temp.resolve("not-a-directory");
        Files.writeString(parentFile, "file");
        Paths paths = start(parentFile.resolve("events.jsonl"));
        assertEquals(500, post("{\"after\":{\"id\":1}}").statusCode());
        assertEquals("write_failed", receipt(paths, 0).path("kind").asText());
    }

    @Test
    void concurrentPostsHaveContiguousReceipts() throws Exception {
        Paths paths = start();
        try (ExecutorService callers = Executors.newFixedThreadPool(20)) {
            List<Callable<Integer>> calls = new ArrayList<>();
            for (int i = 0; i < 20; i++) {
                int id = i;
                calls.add(() -> post("{\"after\":{\"id\":" + id + "},\"op\":\"c\"}").statusCode());
            }
            for (var result : callers.invokeAll(calls)) assertEquals(200, result.get());
        }
        List<String> events = Files.readAllLines(paths.events);
        List<String> receipts = Files.readAllLines(paths.receipts);
        assertEquals(20, events.size());
        assertEquals(20, receipts.size());
        for (String event : events) assertTrue(JSON.readTree(event).isObject());
        for (int i = 0; i < receipts.size(); i++) assertEquals(i + 1, JSON.readTree(receipts.get(i)).path("seq").asInt());
    }

    @Test
    void healthReportsUp() throws Exception {
        start();
        HttpResponse<String> response = client().send(HttpRequest.newBuilder(uri("/health")).GET().build(), HttpResponse.BodyHandlers.ofString());
        assertEquals(200, response.statusCode());
        assertEquals("UP", JSON.readTree(response.body()).path("status").asText());
    }

    private Paths start() throws IOException {
        return start(temp.resolve("events.jsonl"));
    }

    private Paths start(Path events) throws IOException {
        Paths paths = new Paths(events, temp.resolve("receipts.jsonl"));
        receiver = new Receiver(0, paths.events, paths.receipts, temp.resolve("receiver.log"));
        receiver.start();
        return paths;
    }

    private HttpResponse<String> post(String body) throws Exception {
        return client().send(HttpRequest.newBuilder(uri("/events")).POST(HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString());
    }

    private HttpClient client() { return HttpClient.newHttpClient(); }
    private URI uri(String path) { return URI.create("http://127.0.0.1:" + receiver.port() + path); }
    private JsonNode receipt(Paths paths, int line) throws IOException { return JSON.readTree(Files.readAllLines(paths.receipts).get(line)); }

    private record Paths(Path events, Path receipts) { }
}
