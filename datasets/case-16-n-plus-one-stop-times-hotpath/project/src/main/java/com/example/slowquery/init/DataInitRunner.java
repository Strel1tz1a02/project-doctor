package com.example.slowquery.init;

import org.springframework.boot.CommandLineRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;

@Component
public class DataInitRunner implements CommandLineRunner {

    private final JdbcTemplate jdbcTemplate;

    public DataInitRunner(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @Override
    public void run(String... args) {
        Integer tripCount = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM trips", Integer.class);
        if (tripCount != null && tripCount > 0) {
            return;
        }

        int stopTotal = 5000;
        int tripTotal = 50000;
        int stopTimesPerTrip = 10;
        Random random = new Random(42);

        List<Object[]> stops = new ArrayList<>();
        for (int i = 1; i <= stopTotal; i++) {
            stops.add(new Object[]{
                    "STOP" + i,
                    "站点" + i,
                    30.0 + random.nextDouble() * 10.0,
                    100.0 + random.nextDouble() * 20.0
            });
            if (stops.size() >= 5000) {
                jdbcTemplate.batchUpdate("INSERT INTO stops(stop_id, stop_name, stop_lat, stop_lon) VALUES (?, ?, ?, ?)", stops);
                stops.clear();
            }
        }
        if (!stops.isEmpty()) {
            jdbcTemplate.batchUpdate("INSERT INTO stops(stop_id, stop_name, stop_lat, stop_lon) VALUES (?, ?, ?, ?)", stops);
        }

        long now = System.currentTimeMillis();
        List<Object[]> trips = new ArrayList<>();
        for (int i = 1; i <= tripTotal; i++) {
            String tripId = "T" + i;
            String blockId = "B" + (random.nextInt(5000) + 1);
            String routeId = "R" + (random.nextInt(50) + 1);
            Timestamp createdAt = new Timestamp(now - random.nextInt(365 * 24 * 3600) * 1000L);
            trips.add(new Object[]{tripId, blockId, routeId, "S1", "开往站点" + (random.nextInt(stopTotal) + 1), createdAt});
            if (trips.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO trips(trip_id, block_id, route_id, service_id, trip_headsign, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        trips
                );
                trips.clear();
            }
        }
        if (!trips.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO trips(trip_id, block_id, route_id, service_id, trip_headsign, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    trips
            );
        }

        List<Object[]> stopTimes = new ArrayList<>();
        for (int i = 1; i <= tripTotal; i++) {
            String tripId = "T" + i;
            for (int seq = 1; seq <= stopTimesPerTrip; seq++) {
                int hour = 6 + (seq / 4);
                int minute = (seq * 7) % 60;
                String time = String.format("%02d:%02d:00", hour, minute);
                stopTimes.add(new Object[]{tripId, seq, "STOP" + (random.nextInt(stopTotal) + 1), time, time});
            }
            if (stopTimes.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO stop_times(trip_id, stop_sequence, stop_id, arrival_time, departure_time) VALUES (?, ?, ?, ?, ?)",
                        stopTimes
                );
                stopTimes.clear();
            }
        }
        if (!stopTimes.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO stop_times(trip_id, stop_sequence, stop_id, arrival_time, departure_time) VALUES (?, ?, ?, ?, ?)",
                    stopTimes
            );
        }

        System.out.println("测试数据初始化完成：stops=" + stopTotal + ", trips=" + tripTotal
                + ", stop_times=" + (tripTotal * stopTimesPerTrip));
    }
}
