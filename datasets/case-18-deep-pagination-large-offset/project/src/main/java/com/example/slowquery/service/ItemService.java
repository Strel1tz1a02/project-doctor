package com.example.slowquery.service;

import com.example.slowquery.dto.ItemVO;
import com.example.slowquery.dto.PageVO;
import com.example.slowquery.mapper.ItemMapper;
import com.example.slowquery.model.Item;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
public class ItemService {

    private final ItemMapper itemMapper;

    public ItemService(ItemMapper itemMapper) {
        this.itemMapper = itemMapper;
    }

    public PageVO pageItems(int offset, int limit) {
        List<Item> items = itemMapper.findItemsByOffset(limit, offset);
        long total = itemMapper.countItems();

        List<ItemVO> result = new ArrayList<>();
        for (Item item : items) {
            ItemVO vo = new ItemVO();
            vo.setItemId(item.getId());
            vo.setName(item.getName());
            vo.setCategory(item.getCategory());
            vo.setPrice(item.getPrice());
            vo.setCreatedAt(item.getCreatedAt());
            result.add(vo);
        }

        PageVO page = new PageVO();
        page.setOffset(offset);
        page.setLimit(limit);
        page.setTotal(total);
        page.setItems(result);
        return page;
    }
}
