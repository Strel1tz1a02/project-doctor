package com.example.slowquery.service;

import com.example.slowquery.dto.FeedItemVO;
import com.example.slowquery.mapper.FeedMapper;
import com.example.slowquery.model.Post;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
public class FeedService {

    private final FeedMapper feedMapper;

    public FeedService(FeedMapper feedMapper) {
        this.feedMapper = feedMapper;
    }

    public List<FeedItemVO> buildFeed(int size) {
        List<Post> posts = feedMapper.findRecentPosts(size);
        List<FeedItemVO> result = new ArrayList<>();
        for (Post post : posts) {
            FeedItemVO item = new FeedItemVO();
            item.setPostId(post.getId());
            item.setContent(post.getContent());
            item.setAuthorNickname(feedMapper.findNicknameById(post.getAuthorId()));
            result.add(item);
        }
        for (FeedItemVO item : result) {
            item.setLikeCount(feedMapper.countLikesByPostId(item.getPostId()));
        }
        return result;
    }
}
