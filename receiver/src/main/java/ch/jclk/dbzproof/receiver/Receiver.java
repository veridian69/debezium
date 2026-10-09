package ch.jclk.dbzproof.receiver;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeFormatterBuilder;
import java.util.Locale;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.ReentrantLock;
import java.util.logging.FileHandler;
import java.util.logging.Formatter;
import java.util.logging.Handler;
import java.util.logging.Level;
import java.util.logging.LogRecord;
import java.util.logging.Logger;
import java.util.logging.StreamHandler;

public final class Receiver implements AutoCloseable {
    private static final ObjectMapper JSON = new ObjectMapper()
            .disable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
            .disable(DeserializationFeature.USE_BIG_INTEGER_FOR_INTS)
            .enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION);
    private static final DateTimeFormatter MICROSECONDS = new DateTimeFormatterBuilder().appendInstant(6).toFormatter();

    private final HttpServer server;
    private final ExecutorService executor;
    private final Path eventsFile;
    private final Path receiptsFile;
    private final ReentrantLock writeLock = new ReentrantLock();
    private final AtomicLong receiptSequence = new AtomicLong();
    private final Logger logger;
    private final Handler fileHandler;

    public Receiver(int port, Path eventsFile, Path receiptsFile, Path diagFile) throws IOException {
        this.eventsFile = eventsFile;
        this.receiptsFile = receiptsFile;
        this.logger = Logger.getLogger(Receiver.class.getName() + "." + System.identityHashCode(this));
        this.fileHandler = configureLogger(logger, diagFile);
        this.server = HttpServer.create(new InetSocketAddress("0.0.0.0", port), 0);
        this.server.createContext("/", this::handle);
        this.executor = Executors.newFixedThreadPool(4);
        this.server.setExecutor(executor);
    }

    public static void main(String[] args) throws Exception {
        Receiver receiver = new Receiver(
                envPort("PORT", 8080),
                Path.of(System.getenv().getOrDefault("EVENTS_FILE", "/logs/events.jsonl")),
                Path.of(System.getenv().getOrDefault("RECEIPTS_FILE", "/logs/receipts.jsonl")),
                Path.of(System.getenv().getOrDefault("DIAG_FILE", "/logs/receiver.log")));
        Runtime.getRuntime().addShutdownHook(new Thread(receiver::close));
        receiver.start();
    }

    public void start() {
        logger.info(() -> "Starting receiver on " + server.getAddress() + ", events=" + eventsFile + ", receipts=" + receiptsFile);
        server.start();
    }

    public int port() {
        return server.getAddress().getPort();
    }

    private void handle(HttpExchange exchange) throws IOException {
        try (exchange) {
            String path = exchange.getRequestURI().getPath();
            if ("/events".equals(path)) {
                if (!"POST".equals(exchange.getRequestMethod())) {
                    send(exchange, 405, "Method Not Allowed", "text/plain; charset=utf-8");
                } else {
                    handleEvent(exchange);
                }
            } else if ("/health".equals(path)) {
                if (!"GET".equals(exchange.getRequestMethod())) {
                    send(exchange, 405, "Method Not Allowed", "text/plain; charset=utf-8");
                } else {
                    handleHealth(exchange);
                }
            } else {
                send(exchange, 404, "Not Found", "text/plain; charset=utf-8");
            }
        } catch (Exception e) {
            logger.log(Level.SEVERE, "Unhandled request failure", e);
        }
    }

    private void handleEvent(HttpExchange exchange) throws IOException {
        byte[] body = exchange.getRequestBody().readAllBytes();
        String text = new String(body, StandardCharsets.UTF_8);
        if (text.isEmpty() || "null".equals(text)) {
            record(exchange, 204, "tombstone", body.length, null);
            send(exchange, 204, "", "text/plain; charset=utf-8");
            return;
        }

        JsonNode envelope;
        try {
            envelope = JSON.readTree(text);
            if (envelope == null) {
                record(exchange, 204, "tombstone", body.length, null);
                send(exchange, 204, "", "text/plain; charset=utf-8");
                return;
            }
        } catch (Exception e) {
            logger.log(Level.WARNING, "Invalid JSON request: " + e.getMessage());
            record(exchange, 400, "invalid", body.length, null);
            send(exchange, 400, "Invalid JSON", "text/plain; charset=utf-8");
            return;
        }

        String compact;
        try {
            compact = JSON.writeValueAsString(envelope);
        } catch (Exception e) {
            logger.log(Level.WARNING, "Could not serialize parsed JSON", e);
            record(exchange, 400, "invalid", body.length, null);
            send(exchange, 400, "Invalid JSON", "text/plain; charset=utf-8");
            return;
        }

        try {
            writeEvent(compact);
        } catch (Exception e) {
            logger.log(Level.SEVERE, "Could not write event", e);
            record(exchange, 500, "write_failed", body.length, null);
            send(exchange, 500, "Event write failed", "text/plain; charset=utf-8");
            return;
        }
        record(exchange, 200, "event", body.length, summary(envelope));
        send(exchange, 200, "OK", "text/plain; charset=utf-8");
    }

    private void handleHealth(HttpExchange exchange) throws IOException {
        Path parent = eventsFile.toAbsolutePath().getParent();
        boolean writable = parent != null && Files.isDirectory(parent) && Files.isWritable(parent);
        ObjectNode response = JSON.createObjectNode();
        response.put("status", writable ? "UP" : "DOWN");
        response.put("events_file", eventsFile.toString());
        response.put("writable", writable);
        send(exchange, writable ? 200 : 503, JSON.writeValueAsString(response), "application/json; charset=utf-8");
    }

    private void writeEvent(String compact) throws IOException {
        writeLock.lock();
        try {
            appendDurably(eventsFile, compact + "\n");
        } finally {
            writeLock.unlock();
        }
    }

    private void record(HttpExchange exchange, int status, String kind, int bytes, ObjectNode summary) {
        writeLock.lock();
        try {
            ObjectNode receipt = JSON.createObjectNode();
            receipt.put("seq", receiptSequence.incrementAndGet());
            receipt.put("received_at", MICROSECONDS.format(Instant.now()));
            receipt.put("method", exchange.getRequestMethod());
            receipt.put("path", exchange.getRequestURI().getPath());
            receipt.put("status", status);
            receipt.put("kind", kind);
            receipt.put("bytes", bytes);
            ObjectNode headers = receipt.putObject("headers");
            Map<String, String> normalized = new TreeMap<>();
            for (Map.Entry<String, java.util.List<String>> entry : exchange.getRequestHeaders().entrySet()) {
                normalized.put(entry.getKey().toLowerCase(Locale.ROOT), String.join(",", entry.getValue()));
            }
            normalized.forEach(headers::put);
            if (summary != null) {
                receipt.set("summary", summary);
            }
            appendDurably(receiptsFile, JSON.writeValueAsString(receipt) + "\n");
        } catch (Exception e) {
            logger.log(Level.SEVERE, "Could not write receipt", e);
        } finally {
            writeLock.unlock();
        }
    }

    private static void appendDurably(Path path, String value) throws IOException {
        try (FileChannel channel = FileChannel.open(path, StandardOpenOption.CREATE, StandardOpenOption.WRITE, StandardOpenOption.APPEND)) {
            ByteBuffer bytes = StandardCharsets.UTF_8.encode(value);
            while (bytes.hasRemaining()) {
                channel.write(bytes);
            }
            channel.force(true);
        }
    }

    private static ObjectNode summary(JsonNode envelope) {
        ObjectNode result = JSON.createObjectNode();
        copy(envelope, "op", result, "op");
        JsonNode source = envelope.path("source");
        copy(source, "schema", result, "schema");
        copy(source, "table", result, "table");
        JsonNode row = envelope.path("after");
        if (!row.isObject()) {
            row = envelope.path("before");
        }
        if (row.isObject() && row.has("id") && !row.get("id").isNull()) {
            result.putObject("key").set("id", row.get("id"));
        }
        return result.isEmpty() ? null : result;
    }

    private static void copy(JsonNode from, String sourceName, ObjectNode target, String targetName) {
        if (from != null && from.has(sourceName) && !from.get(sourceName).isNull()) {
            target.set(targetName, from.get(sourceName));
        }
    }

    private static void send(HttpExchange exchange, int status, String body, String contentType) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", contentType);
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream output = exchange.getResponseBody()) {
            output.write(bytes);
        }
    }

    private static int envPort(String name, int defaultValue) {
        String value = System.getenv(name);
        return value == null || value.isBlank() ? defaultValue : Integer.parseInt(value);
    }

    private static Handler configureLogger(Logger logger, Path diagFile) throws IOException {
        logger.setUseParentHandlers(false);
        logger.setLevel(Level.INFO);
        Files.createDirectories(diagFile.toAbsolutePath().getParent());
        Formatter formatter = new SingleLineFormatter();
        FileHandler file = new FileHandler(diagFile.toString(), true);
        file.setFormatter(formatter);
        logger.addHandler(file);
        StreamHandler stdout = new StreamHandler(System.out, formatter) {
            @Override public synchronized void publish(LogRecord record) { super.publish(record); flush(); }
        };
        stdout.setLevel(Level.ALL);
        logger.addHandler(stdout);
        return file;
    }

    @Override
    public void close() {
        server.stop(0);
        executor.shutdownNow();
        fileHandler.close();
    }

    private static final class SingleLineFormatter extends Formatter {
        @Override public String format(LogRecord record) {
            String text = MICROSECONDS.format(Instant.ofEpochMilli(record.getMillis())) + " " + record.getLevel() + " " + formatMessage(record);
            if (record.getThrown() != null) {
                text += " " + record.getThrown().toString();
                for (StackTraceElement element : record.getThrown().getStackTrace()) text += " at " + element;
            }
            return text.replace('\n', ' ').replace('\r', ' ') + System.lineSeparator();
        }
    }
}
