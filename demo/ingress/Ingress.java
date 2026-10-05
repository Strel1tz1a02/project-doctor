import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Fixed-destination TCP ingress; neither the client nor target can select a destination. */
public final class Ingress {
    public static void main(String[] args) throws IOException {
        ExecutorService workers = Executors.newCachedThreadPool();
        try (ServerSocket listener = new ServerSocket(8080)) {
            while (true) {
                Socket accepted = listener.accept();
                workers.execute(() -> {
                    try (Socket client = accepted; Socket upstream = new Socket()) {
                        upstream.connect(new InetSocketAddress("app", 8080), 5000);
                        client.setSoTimeout(30000);
                        upstream.setSoTimeout(30000);
                        workers.execute(() -> {
                            try {
                                client.getInputStream().transferTo(upstream.getOutputStream());
                                upstream.shutdownOutput();
                            } catch (IOException ignored) { /* peer closed */ }
                        });
                        upstream.getInputStream().transferTo(client.getOutputStream());
                    } catch (IOException error) {
                        System.err.println("ingress connection failed: " + error.getClass().getSimpleName());
                    }
                });
            }
        } finally {
            workers.shutdownNow();
        }
    }
}
