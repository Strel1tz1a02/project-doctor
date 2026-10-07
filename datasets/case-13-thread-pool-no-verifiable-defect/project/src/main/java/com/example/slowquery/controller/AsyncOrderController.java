package com.example.slowquery.controller;

import com.example.slowquery.dto.OrderVO;
import com.example.slowquery.service.AsyncOrderService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/orders")
public class AsyncOrderController {

    private final AsyncOrderService asyncOrderService;

    public AsyncOrderController(AsyncOrderService asyncOrderService) {
        this.asyncOrderService = asyncOrderService;
    }

    @GetMapping("/async-recent")
    public List<OrderVO> asyncRecent(@RequestParam Long userId,
                                     @RequestParam(defaultValue = "20") int size) {
        return asyncOrderService.asyncRecent(userId, size);
    }
}
