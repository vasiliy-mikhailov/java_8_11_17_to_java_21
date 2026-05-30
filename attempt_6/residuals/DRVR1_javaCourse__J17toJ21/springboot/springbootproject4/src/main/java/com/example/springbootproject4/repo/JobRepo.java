package com.example.springbootproject4.repo;

import java.util.ArrayList;
import java.util.List;

import org.springframework.stereotype.Repository;

import com.example.springbootproject4.model.Job;

@Repository
public class JobRepo {
    public List<Job> jobs = new ArrayList<>();

    public JobRepo() {
        Job job1 = new Job(1, "telemarketer", 1000);
        Job job2 = new Job(2, "sales", 1300);
        jobs.add(job1);
        jobs.add(job2);
    }

    public List<Job> getAllJobs() {
        return jobs;
    }

    public Job getJobById(long id) {
        for (Job job : jobs) {
            if (job.getId() == id) {
                return job;
            }
        }
        return null;
    }

    public Job createJob(Job job) {
        jobs.add(job);
        return getJobById(job.getId());
    }

    public Job updateJob(Job job) {
        for (Job searchedJob : jobs) {
            if (searchedJob.getId() == job.getId()) {
                searchedJob.setName(job.getName());
                searchedJob.setSalary(job.getSalary());
                return searchedJob;
            }
        }
        return null;
    }

    public boolean deleteJob(Job job) {
        for (Job searchedJob : jobs) {
            if (searchedJob.getId() == job.getId()) {
                jobs.remove(searchedJob);
                return true;
            }
        }
        return false;
    }
}
